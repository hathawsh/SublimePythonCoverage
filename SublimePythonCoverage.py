# bootstrap
import os
import sys
plugin_path = os.path.dirname(__file__)
if not os.path.exists(os.path.join(plugin_path, 'coverage')):
    # Fetch the coverage package
    print('SublimePythonCoverage installing the coverage package.')

    import tarfile
    from hashlib import md5

    try:
        # Python 3
        from io import BytesIO
        from urllib.request import urlopen
    except ImportError:
        # Python 2
        from StringIO import StringIO as BytesIO
        from urllib2 import urlopen

    SOURCE = (
        'https://pypi.python.org/packages/0b/e1/'
        '190ef1a264144c9b073b7353c259ca5431b5ddc8861b452e858fcbd0e9de'
        '/coverage-4.4.2.tar.gz')
    MD5SUM = '29a9fe85377e0f7327cf5db1e335483f'

    payload = urlopen(SOURCE).read()
    if md5(payload).hexdigest() != MD5SUM:
        raise ImportError('Invalid checksum.')

    tar = tarfile.open(mode='r:gz', fileobj=BytesIO(payload))
    for m in tar.getmembers():
        if not m.name.startswith('coverage-4.4.2/coverage/'):
            continue
        m.name = '/'.join(m.name.split('/')[2:])
        tar.extract(m, os.path.join(plugin_path, 'coverage'))

    from coverage import Coverage  # Test the import
    print('SublimePythonCoverage successfully installed the coverage package.')
# end bootstrap

if plugin_path not in sys.path:
    sys.path.insert(0, plugin_path)


import sublime
import sublime_plugin
from coverage import Coverage
from coverage.files import FnmatchMatcher

try:
    # Python 2
    basestring
except NameError:
    # Python 3
    basestring = str


def find(base, rel, access=os.R_OK):
    if not isinstance(rel, basestring):
        rel = os.path.join(*rel)
    while True:
        path = os.path.join(base, rel)
        if os.access(path, access):
            return path
        baseprev = base
        base = os.path.dirname(base)
        if not base or base == baseprev:
            return


def find_cmd(base, cmd):
    return find(base, ('bin', cmd), os.X_OK)


def find_tests(fname):
    dirname = os.path.dirname(fname)
    init = os.path.join(dirname, '__init__.py')
    if not os.path.exists(init):
        # not a package; run tests for the file
        return fname

    setup = find(dirname, 'setup.py')
    if setup:
        # run tests for the whole distribution
        return os.path.dirname(setup)

    # run tests for the package
    return os.path.dirname(fname)


class SublimePythonCoverageListener(sublime_plugin.EventListener):
    """Highlight uncovered lines when a Python file is loaded."""

    def on_load(self, view):
        if 'source.python' not in view.scope_name(0):
            return

        view.run_command('show_python_coverage')


class ShowPythonCoverageCommand(sublime_plugin.TextCommand):
    """Highlight uncovered lines in the current file.

    Show the info from a previous coverage run.
    """

    def run(self, edit):
        view = self.view
        view.erase_regions('SublimePythonCoverage')
        fname = view.file_name()
        if not fname or not fname.endswith('.py'):
            return

        cov_file = find(fname, '.coverage')
        if not cov_file:
            print('No .coverage file found near %s' % fname)
            return
        else:
            print('Reading coverage data from %s' % cov_file)

        config_file = os.path.join(os.path.dirname(cov_file), '.coveragerc')

        if find(fname, '.coverage-noisy'):
            flags = sublime.DRAW_EMPTY | sublime.DRAW_OUTLINED
        else:
            flags = sublime.HIDDEN

        # run analysis and find uncovered lines
        cov = Coverage(data_file=cov_file, config_file=config_file)
        outlines = []
        cov.load()
        if not cov.omit or not FnmatchMatcher(cov.omit).match(fname):
            f, s, excluded, missing, m = cov.analysis2(fname)
            for line in missing:
                outlines.append(view.full_line(view.text_point(line - 1, 0)))

        # update highlighted regions
        view.add_regions('SublimePythonCoverage', outlines,
                         'coverage.missing', 'bookmark', flags)


# Manually import the module containing the ExecCommand class
# since it's in a module whose name is a Python keyword.
try:
    # Sublime Text 3
    import Default
    ExecCommand = getattr(Default, 'exec').ExecCommand
except ImportError:
    # Sublime Text 2
    ExecCommand = __import__('exec').ExecCommand


class TestExecCommand(ExecCommand):
    """An extension of the default build system. Shows coverage at the end.

    Also tries to tell the test runner exactly which function and class the
    user is pointing at so it can run a specific pretest.
    """

    runner = None

    def cmd(self, runner, testpath):
        NotImplemented

    def run(self, **kw):
        if 'cmd' not in kw:
            fname = self.window.active_view().file_name()
            env = {'TESTFILE': fname}

            if fname.endswith('.py'):
                try:
                    view = self.window.active_view()
                    content = view.substr(sublime.Region(0, view.size()))
                    point = view.sel()[0].begin()
                    row, _col = view.rowcol(point)
                    decls = list_decls(content, fname)
                    bottom_decl = find_decl_for_row(decls, row)
                    attrs = []
                    for decl in reversed(list(bottom_decl.lineage())):
                        if isinstance(decl, ClassDecl):
                            attrs.append(decl.name)
                        elif isinstance(decl, FuncDecl):
                            attrs.append(decl.name)
                            break
                        else:
                            break
                    if attrs:
                        env['TESTATTR'] = '.'.join(attrs)
                except Exception as e:
                    print(
                        "SublimePythonCoverage parser failed: "
                        "%s %s" % (type(e), e))

            # look for a virtualenv with nosetests, py.test etc
            runner = find_cmd(fname, self.runner)
            if runner is None:
                # no virtualenv; maybe there's a global one
                runner = self.runner

            testpath = find_tests(fname)
            if os.path.isdir(testpath):
                kw['working_dir'] = testpath
            else:
                kw['working_dir'] = os.path.dirname(testpath)

            kw['cmd'] = self.cmd(runner, testpath)
            kw['env'] = env

        super(TestExecCommand, self).run(**kw)

    def finish(self, proc):
        super(TestExecCommand, self).finish(proc)
        for view in self.window.views():
            view.run_command('show_python_coverage')


class NoseExecCommand(TestExecCommand):
    """An extension of the default build system using the Python Nose test
       runner to generate coverage information."""

    runner = 'nosetests'

    def cmd(self, runner, testpath):
        return [runner, '--with-coverage', testpath]


class PytestExecCommand(TestExecCommand):
    """An extension of the default build system using the py.test test
       runner to generate coverage information."""

    runner = 'py.test'

    def cmd(self, runner, testpath):
        return [runner]


# The code below is a little library for discovering the method
# and class name the user is pointing at.


import ast
import re
import weakref


empty_line_re = re.compile(r'\s*$')


class Decl(object):
    """A function or class declaration statement."""
    def __init__(self, name, first_row, last_row=None, children=None):
        self.name = name
        self.first_row = first_row
        # Note: last_row includes the blank rows after the declaration.
        self.last_row = last_row
        self.children = children or []
        self.parent_ref = None  # A weakref.ref

    def lineage(self):
        decl = self
        while decl is not None:
            yield decl
            parent = decl.parent_ref()
            if parent is None or isinstance(parent, ModuleDecl):
                break
            decl = parent

    def __repr__(self):
        return ('{0}({1!r}, {2!r}, {3!r}, {4!r})'
                .format(self.__class__.__name__,
                        self.name,
                        self.first_row,
                        self.last_row,
                        self.children))


class ModuleDecl(Decl):
    pass


class ClassDecl(Decl):
    pass


class FuncDecl(Decl):
    pass


class Visitor(ast.NodeVisitor):
    """Create a Decl tree from a Python abstract syntax tree."""

    def __init__(self, lines):
        self.parent = self.top = ModuleDecl('', 0)
        self.lines = lines
        self.last_lineno = 1
        self.closing_decls = []

    def visitdecl(self, node, cls):
        decl = cls(node.name, node.lineno - 1)
        parent = self.parent
        decl.parent_ref = weakref.ref(parent)
        parent.children.append(decl)
        self.last_lineno = node.lineno
        self.parent = decl
        self.generic_visit(node)
        self.parent = parent
        decl.last_row = self.last_lineno - 1
        self.closing_decls.append(decl)

    def visit_FunctionDef(self, node):
        self.close_decls(node.lineno)
        self.visitdecl(node, FuncDecl)

    def visit_ClassDef(self, node):
        self.close_decls(node.lineno)
        self.visitdecl(node, ClassDecl)

    def generic_visit(self, node):
        if hasattr(node, 'lineno'):
            self.close_decls(node.lineno)
            self.last_lineno = max(self.last_lineno, node.lineno)
        super(Visitor, self).generic_visit(node)

    def close_decls(self, new_lineno):
        decls = self.closing_decls
        if decls:
            # Change the range of the closing declarations to include
            # multi-line expressions, but not blank lines.
            # To compute last_row, subtract 1 from new_lineno because
            # the previous declaration ends on the line before;
            # subtract 1 again because rows are zero-based while lines are
            # one-based.
            last_row = new_lineno - 2
            while last_row > 0 and last_row < len(self.lines):
                line = self.lines[last_row]
                if not line or empty_line_re.match(line):
                    # Ignore an empty line.
                    last_row -= 1
                else:
                    break
            for decl in decls:
                decl.last_row = max(last_row, decl.last_row)
            del self.closing_decls[:]


def list_decls(content, filename):
    """List the nested declarations in a module."""
    node = ast.parse(content, filename)
    lines = content.splitlines()
    visitor = Visitor(lines)
    visitor.visit(node)
    if visitor.closing_decls:
        visitor.close_decls(len(lines) + 1)
    return visitor.top.children


def find_decl_for_row(decls, row):
    for decl in decls:
        if row >= decl.first_row and row <= decl.last_row:
            child = find_decl_for_row(decl.children, row)
            if child is not None:
                return child
            else:
                return decl
    return None
