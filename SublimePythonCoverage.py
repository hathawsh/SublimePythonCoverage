import os
import sublime, sublime_plugin

from coverage import coverage

PLUGIN_FILE = os.path.abspath(__file__)


def find(base, rel, access=os.R_OK):
    if not isinstance(rel, basestring):
        rel = os.path.join(*rel)
    while 1:
        path = os.path.join(base, rel)
        if os.access(path, access):
            return path
        base = os.path.dirname(base)
        if not base or base == '/':
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
    """Event listener to highlight uncovered lines when a Python file is loaded."""

    def on_load(self, view):
        if 'source.python' not in view.scope_name(0):
            return

        view.run_command('show_python_coverage')


class ShowPythonCoverageCommand(sublime_plugin.TextCommand):
    """Highlight uncovered lines in the current file based on a previous coverage run."""

    def run(self, edit):
        view = self.view
        fname = view.file_name()
        if not fname:
            return

        cov_file = find(fname, '.coverage')
        if not cov_file:
            print 'Could not find .coverage file.'
            return

        # run analysis and find uncovered lines
        cov = coverage(data_file=cov_file)
        cov_dir = os.path.dirname(cov_file)
        os.chdir(cov_dir)
        relpath = os.path.relpath(fname, cov_dir)
        cov.load()
        f, s, excluded, missing, m = cov.analysis2(relpath)
        outlines = []
        for line in missing:
            outlines.append(view.full_line(view.text_point(line - 1, 0)))

        # update highlighted regions
        view.erase_regions('SublimePythonCoverage')
        view.add_regions('SublimePythonCoverage', outlines, 'comment', 
            sublime.DRAW_EMPTY | sublime.DRAW_OUTLINED)


# manually import the module containing ST2's default build command,
# since it's in a module whose name is a Python keyword :-s
ExecCommand = __import__('exec').ExecCommand
class NoseExecCommand(ExecCommand):
    """An extension of the default build system which shows coverage at the end.

    Used by the Python Nose build system.
    """

    def run(self, **kw):
        if 'cmd' not in kw:
            fname = self.window.active_view().file_name()

            # look for a virtualenv with nosetests
            nose = find_cmd(fname, 'nosetests')
            if nose is None:
                # no virtualenv; maybe there's a global one
                nose = 'nosetests'

            testpath = find_tests(fname)
            if os.path.isdir(testpath):
                kw['working_dir'] = testpath
            else:
                kw['working_dir'] = os.path.dirname(testpath)

            kw['cmd'] = [nose, '--with-coverage', testpath]

        super(NoseExecCommand, self).run(**kw)

    def finish(self, proc):
        super(NoseExecCommand, self).finish(proc)
        for view in self.window.views():
            view.run_command('show_python_coverage')


# TODO:
# - install coverage egg via helper script
# - instructions on installation
# - documentation
# - test coverage!