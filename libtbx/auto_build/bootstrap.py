#!/usr/bin/env python
# -*- mode: python; coding: utf-8; indent-tabs-mode: nil; python-indent: 2 -*-
from __future__ import division
import os, os.path, posixpath, ntpath
import optparse
import re
import shutil
import socket as pysocket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import urllib2
import urlparse
import zipfile

windows_remove_list = []

rosetta_version_tar_bundle="rosetta_src_3.7_bundle"
rosetta_version_directory='rosetta_src_2016.32.58837_bundle'
# LICENSE REQUIRED
afitt_version="AFITT-2.4.0.4-redhat-RHEL7-x64" #binary specific to cci-vm-1
amber_version='ambertools-18' # same as circle download file
amber_dir='amber18'
envs = {
  "AMBERHOME"           : ["modules", "amber"],
  "PHENIX_ROSETTA_PATH" : ["modules", "rosetta"],
  "OE_EXE"              : ["modules", "openeye", "bin"],
  "OE_LICENSE"          : ["oe_license.txt"], # needed for license
}

# To download this file:
# wget https://raw.githubusercontent.com/cctbx/cctbx_project/master/libtbx/auto_build/bootstrap.py
# or
# curl https://raw.githubusercontent.com/cctbx/cctbx_project/master/libtbx/auto_build/bootstrap.py > bootstrap.py

# To get the version before the switch to git:
# svn export -r 25697 svn://svn.code.sf.net/p/cctbx/code/trunk/libtbx/auto_build/bootstrap.py

# Utility function to be executed on slave machine or called directly by standalone bootstrap script
def tar_extract(workdir, archive, modulename=None):
  try:
    # delete tar target folder if it exists
    if modulename and os.path.exists(modulename):
      def remShut(*args):
        func, path, _ = args # onerror returns a tuple containing function, path and exception info
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        os.remove(path)
      shutil.rmtree(modulename, onerror=remShut)
      # hack to work around possible race condition on Windows where deleted files may briefly
      # exist as phantoms and result in "access denied" error by subsequent IO operations
      cnt=0
      while os.path.exists(modulename):
        time.sleep(1)
        cnt = cnt + 1
        if cnt > 5:
          break
    # using tarfile module rather than unix tar command which is not platform independent
    if sys.hexversion >= 0x02060000:
      tar = tarfile.open(os.path.join(workdir, archive), errorlevel=2)
      tar.extractall(path=workdir)
    else:
      import copy
      import operator
      tar = tarfile.open(os.path.join(workdir, archive))
      directories = []
      for tarinfo in tar.getmembers():
        if tarinfo.isdir():
          # Extract directories with a safe mode.
          directories.append(tarinfo)
          tarinfo = copy.copy(tarinfo)
          tarinfo.mode = 0700
        tar.extract(tarinfo, workdir)
        # Reverse sort directories.
        directories.sort(key=operator.attrgetter('name'))
        directories.reverse()
        # Set correct owner, mtime and filemode on directories.
        for tarinfo in directories:
          dirpath = os.path.join(workdir, tarinfo.name)
          tar.chown(tarinfo, dirpath)
          tar.utime(tarinfo, dirpath)
          tar.chmod(tarinfo, dirpath)
    tarfoldername = os.path.join(workdir, os.path.commonprefix(tar.getnames()).split('/')[0])
    tar.close()
    # take full permissions on all extracted files
    module = os.path.join(workdir, tarfoldername)
    for root, dirs, files in os.walk(module):
      for fname in files:
        full_path = os.path.join(root, fname)
        os.chmod(full_path, stat.S_IREAD | stat.S_IWRITE)
    # rename to expected folder name, e.g. boost_hot -> boost
    # only rename if folder names differ
    if modulename:
      if modulename != tarfoldername:
        os.rename(tarfoldername, modulename)
  except Exception, e:
    raise Exception("Extracting tar archive resulted in error: " + str(e) + "\n" \
      + traceback.format_exc())
    return 1
  return 0

# Mock commands to run standalone, without buildbot.
class ShellCommand(object):
  def __init__(self, **kwargs):
    self.kwargs = kwargs

  def get_command(self):
    return self.kwargs['command']

  def get_description(self):
    if 'description' in self.kwargs:
      return self.kwargs['description']
    return None

  def get_workdir(self):
    return self.kwargs.get('workdir', 'build')

  def get_environment(self):
    # gets environment from kwargs
    env = self.kwargs.get('env', None)
    if env:
      for key, item in env.items():
        env[key] = os.path.abspath(item)
      rc = os.environ
      rc.update(env)
      env=rc
    return env

  def run(self):
    t0=time.time()
    command = self.get_command()
    description = self.get_description()
    workdir = self.get_workdir()
    env = self.get_environment()
    if not self.kwargs.get("quiet", False):
      if description:
        print "===== Running in %s:"%workdir, description
      else:
        print "===== Running in %s:"%workdir, " ".join(command)
    if workdir:
      try:
        os.makedirs(workdir)
      except OSError:
        pass
    if command[0] == 'tar':
      # don't think any builders explicitly calls tar but leave it here just in case
      modname = None
      if len(command) > 3 and command[3]:
        modname = command[3]
      return tar_extract(workdir, command[2], modname)
    if command[0] == 'rm':
      # XXX use shutil rather than rm which is not platform independent
      for directory in command[2:]:
        if os.path.exists(directory):
          print 'Deleting directory : %s' % directory
          try: shutil.rmtree(directory)
          except OSError, e:
            print "Strangely couldn't delete %s" % directory
      return 0
    if 0:
      print 'command',command
      print 'workdir',workdir
      print 'env',env
      print os.environ.get("PATH", None)
    try:
      #if not os.path.isabs(command[0]):
        # executable path isn't located relative to workdir
      #  command[0] = os.path.join(workdir, command[0])
      stderr, stdout = None, None
      if self.kwargs.get("silent", False):
        stderr = stdout = open(os.devnull, 'wb')
      p = subprocess.Popen(
        args=command,
        cwd=workdir,
        stdout=stdout,
        stderr=stderr,
        env=env,
      )
    except Exception, e: # error handling
      if not self.kwargs.get('haltOnFailure'):
        return 1
      if isinstance(e, OSError):
        if e.errno == 2:
          executable = os.path.normpath(os.path.join(workdir, command[0]))
          raise RuntimeError("Could not run %s: File not found" % executable)
      if 'child_traceback' in dir(e):
        print "Calling subprocess resulted in error; ", e.child_traceback
      raise e

    p.wait()
    if p.returncode != 0 and self.kwargs.get('haltOnFailure'):
      print "Process failed with return code %s"%(p.returncode)
      sys.exit(1)
    if 0:
      if description:
        outl = "%s - %s" % (workdir, description)
      else:
        outl = "%s - %s" % (workdir, " ".join(command))
      print '===== Time to %s : %0.1f' % (outl, time.time()-t0)
    return p.returncode

class Toolbox(object):
  @staticmethod
  def download_to_file(url, file, log=sys.stdout, status=True, cache=True):
    """Downloads a URL to file. Returns the file size.
       Returns -1 if the downloaded file size does not match the expected file
       size
       Returns -2 if the download is skipped due to the file at the URL not
       being newer than the local copy (identified by A. matching timestamp and
       size, or B. matching etag).
    """

    # Create directory structure if necessary
    if os.path.dirname(file):
      try:
        os.makedirs(os.path.dirname(file))
      except Exception, e:
        pass

    localcopy = os.path.isfile(file)

    # Get existing ETag, if present
    etag = None
    tagfile = '%s/.%s.etag' % os.path.split(os.path.abspath(file))
    if cache and os.path.isfile(tagfile):
      if not localcopy:
        # Having an ETag without a file is pointless
        os.remove(tagfile)
      else:
        tf = open(tagfile, 'r')
        etag = tf.readline()
        tf.close()

    try:
      import ssl
      from ssl import SSLError
    except ImportError:
      ssl = None
      SSLError = None

    # Open connection to remote server
    try:
      if sys.platform == "win32" and 'lbl.gov' in url:
# Downloading from http://cci.lbl.gov/cctbx_dependencies caused
# SSL: CERTIFICATE_VERIFY_FAILED error on Windows only as of today (why?).
# Quick and dirty hack to disable ssl certificate verification.
        try:
          _create_unverified_https_context = ssl._create_unverified_context
        except AttributeError:
          # Legacy Python that doesn't verify HTTPS certificates by default
          pass
        except NameError:
          # ssl module was not loaded
          pass
        else:
          # Handle target environment that doesn't support HTTPS verification
          ssl._create_default_https_context = _create_unverified_https_context
      url_request = urllib2.Request(url)
      if etag:
        url_request.add_header("If-None-Match", etag)
      if localcopy and (sys.hexversion >= 0x02060000):
        # Shorten timeout to 7 seconds if a copy of the file is already present
        # This is only supported in python >=2.6
        socket = urllib2.urlopen(url_request, None, 7)
      else:
        socket = urllib2.urlopen(url_request)
    except SSLError, e:
      # This could be a timeout
      if localcopy:
        # Download failed for some reason, but a valid local copy of
        # the file exists, so use that one instead.
        log.write("%s\n" % str(e))
        return -2
      # otherwise pass on the error message
      raise
    except (pysocket.timeout, urllib2.HTTPError), e:
      if isinstance(e, urllib2.HTTPError) and etag and e.code == 304:
        # When using ETag. a 304 error means everything is fine
        log.write("local copy is current (etag)\n")
        return -2
      if localcopy:
        # Download failed for some reason, but a valid local copy of
        # the file exists, so use that one instead.
        log.write("%s\n" % str(e))
        return -2
      # otherwise pass on the error message
      raise
    except urllib2.URLError, e:
      if localcopy:
        # Download failed for some reason, but a valid local copy of
        # the file exists, so use that one instead.
        log.write("%s\n" % str(e))
        return -2
      # if url fails to open, try using curl
      # temporary fix for old OpenSSL in system Python on macOS
      # https://github.com/cctbx/cctbx_project/issues/33
      subprocess.call(['/usr/bin/curl', '-o', file, url], stdout=sys.stdout,
                      stderr=sys.stderr)
      socket = None     # prevent later socket code from being run
      received = 1      # satisfy (filesize > 0) checks later on

    if (socket is not None):
      try:
        file_size = int(socket.info().getheader('Content-Length'))
      except Exception:
        file_size = 0

      if os.path.isfile(tagfile):
        # ETag did not match, so delete any existing ETag.
        os.remove(tagfile)

      remote_mtime = 0
      try:
        remote_mtime = time.mktime(socket.info().getdate('last-modified'))
      except Exception:
        pass

      if (file_size > 0):
        if (remote_mtime > 0):
          # check if existing file matches remote size and timestamp
          try:
            (mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime) = os.stat(file)
            if (size == file_size) and (remote_mtime == mtime):
              log.write("local copy is current\n")
              socket.close()
              return -2
          except Exception:
            # proceed with download if timestamp/size check fails for any reason
            pass

        hr_size = (file_size, "B")
        if (hr_size[0] > 500): hr_size = (hr_size[0] / 1024, "kB")
        if (hr_size[0] > 500): hr_size = (hr_size[0] / 1024, "MB")
        log.write("%.1f %s\n" % hr_size)
        if status:
          log.write("    [0%")
          log.flush()

      received = 0
      block_size = 8192
      progress = 1
      # Allow for writing the file immediately so we can empty the buffer
      tmpfile = file + '.tmp'

      f = open(tmpfile, 'wb')
      while 1:
        block = socket.read(block_size)
        received += len(block)
        f.write(block)
        if status and (file_size > 0):
          while (100 * received / file_size) > progress:
            progress += 1
            if (progress % 20) == 0:
              log.write("%d%%" % progress)
            elif (progress % 2) == 0:
              log.write(".")
            log.flush()

        if not block: break
      f.close()
      socket.close()

      if status and (file_size > 0):
        log.write("]\n")
      else:
        log.write("%d kB\n" % (received / 1024))
      log.flush()

      # Do not overwrite file during the download. If a download temporarily fails we
      # may still have a clean, working (yet older) copy of the file.
      shutil.move(tmpfile, file)

      if (file_size > 0) and (file_size != received):
        return -1

      if remote_mtime > 0:
        # set file timestamp if timestamp information is available
        from stat import ST_ATIME
        st = os.stat(file)
        atime = st[ST_ATIME] # current access time
        os.utime(file,(atime,remote_mtime))

      if cache and socket.info().getheader('ETag'):
        # If the server sent an ETAG, then keep it alongside the file
        open(tagfile, 'w').write(socket.info().getheader('ETag'))

    return received

  @staticmethod
  def unzip(archive, directory, trim_directory=0, verbose=False):
    '''unzip a file into a directory. Requires Python 2.6.'''
    if verbose:
      print "===== Installing %s into %s" % (archive, directory)
    if not zipfile.is_zipfile(archive):
      raise Exception("%s is not a valid .zip file" % archive)
    z = zipfile.ZipFile(archive, 'r')
    for member in z.infolist():
      is_directory = member.filename.endswith('/')
      filename = os.path.join(*member.filename.split('/')[trim_directory:])
      if filename != '':
        filename = os.path.normpath(filename)
        if '../' in filename:
          raise Exception('Archive %s contains invalid filename %s' % (archive, filename))
        filename = os.path.join(directory, filename)
        upperdirs = os.path.dirname(filename)
        try:
          if is_directory and not os.path.exists(filename):
            os.makedirs(filename)
          elif upperdirs and not os.path.exists(upperdirs):
            os.makedirs(upperdirs)
        except Exception, e: pass
        if not is_directory:
          source = z.open(member)
          target = file(filename, "wb")
          shutil.copyfileobj(source, target)
          target.close()
          source.close()

          # Preserve executable permission, if set
          unix_executable = member.external_attr >> 16 & 73
            # Python 2.5 does not allow octal notation with 0o prefix
            # rwxrwxrwx => --x--x--x => 0o111 => 73
          if unix_executable:
            mode = os.stat(filename).st_mode
            mode |= (mode & 292) >> 2 # copy R bits to X
             # r--r--r-- => 0o444 => 292
            os.chmod(filename, mode)
    z.close()

  @staticmethod
  def set_git_repository_config_to_rebase(config):
    with open(config, 'r') as fh:
      cfg = fh.readlines()

    branch, remote, rebase = False, False, False
    insertions = []
    for n, line in enumerate(cfg):
      if line.startswith('['):
        if branch and remote and not rebase:
          insertions.insert(0, (n, branch))
        if line.startswith('[branch'):
          branch = line.split('"')[1]
        else:
          branch = False
        remote, rebase = False, False
      if re.match('remote\s*=\s*', line.strip()):
        remote = True
      if re.match('rebase\s*=\s*', line.strip()):
        rebase = True
    if branch and remote and not rebase:
      insertions.insert(0, (n + 1, branch))
    for n, branch in insertions:
      print "  setting branch %s to rebase" % branch
      cfg.insert(n, '\trebase = true\n')
    with open(config, 'w') as fh:
      fh.write("".join(cfg))

  @staticmethod
  def git(module, parameters, destination=None, use_ssh=False, verbose=False, reference=None):
    '''Retrieve a git repository, either by running git directly
       or by downloading and unpacking an archive.'''
    git_available = True
    try:
      subprocess.call(['git', '--version'], stdout=open(os.devnull, 'wb'), stderr=open(os.devnull, 'wb'))
    except OSError:
      git_available = False

    if destination is None:
      destination = os.path.join('modules', module)
    destpath, destdir = os.path.split(destination)

    if os.path.exists(destination):
      if git_available and os.path.exists(os.path.join(destination, '.git')):
        if not open(os.path.join(destination, '.git', 'HEAD'), 'r').read().startswith('ref:'):
          print "WARNING: Can not update existing git repository! You are not on a branch."
          print "This may be legitimate when run eg. via Jenkins, but be aware that you cannot commit any changes"
          return

        else:
          # This may fail for unclean trees and merge problems. In this case manual
          # user intervention will be required.
          # For the record, you can clean up the tree and *discard ALL changes* with
          #   git reset --hard origin/master
          #   git clean -dffx
          return ShellCommand(
            command=['git', 'pull', '--rebase'], workdir=destination, silent=False, haltOnFailure=True).run()

      print "Existing non-git directory -- don't know what to do. skipping: %s" % module
      if ('cctbx_project.git' in parameters[0]):
        print '\n' + '=' * 80 + '\nCCTBX moved to git on November 22, 2016.\n\nTo update cctbx_project to the last available subversion revision please run "svn update" while in the cctbx_project directory.\n' + '*'*80 + '\n'
      return

    if isinstance(parameters, basestring):
      parameters = [ parameters ]
    git_parameters = []
    for source_candidate in parameters:
      if source_candidate.startswith('-'):
        git_parameters = source_candidate.split(' ')
        continue
      if (not source_candidate.lower().startswith('http') and not use_ssh):
        continue
      if source_candidate.lower().endswith('.git'):
        if not git_available:
          continue
        reference_parameters = []
        if reference is not None:
          if os.path.exists(reference) and os.path.exists(os.path.join(reference, '.git')):
            reference_parameters = [ '--reference', reference ]
        cmd = [ 'git', 'clone', '--recursive' ] + git_parameters + [ source_candidate, destdir ] + reference_parameters
        if verbose:
          cmd = cmd + [ '--progress', '--verbose' ]
        returncode = ShellCommand(
          command=cmd, workdir=destpath, silent=False
        ).run()
        if returncode:
          return returncode # no point trying to continue on error
        if reference_parameters:
          # Sever the link between checked out and reference repository
          cmd = [ 'git', 'repack', '-a', '-d' ]
          returncode = ShellCommand(
            command=cmd, workdir=destination, silent=False
          ).run()
          try:
            os.remove(os.path.join(destination, '.git', 'objects', 'info', 'alternates'))
          except OSError:
            returncode = 1
        Toolbox.set_git_repository_config_to_rebase(os.path.join(destination, '.git', 'config'))
        return returncode
      filename = "%s-%s" % (module,
                            urlparse.urlparse(source_candidate)[2].split('/')[-1])
      filename = os.path.join(destpath, filename)
      if verbose:
        print "===== Downloading %s: " % source_candidate,
      Toolbox.download_to_file(source_candidate, filename)
      Toolbox.unzip(filename, destination, trim_directory=1, verbose=verbose)
      return

    error = "Cannot satisfy git dependency for module %s: None of the sources are available." % module
    if not git_available:
      print error
      error = "A git installation has not been found."
    raise Exception(error)

class cleanup_ext_class(object):
  def __init__(self, filename_ext, workdir=None, walk=True):
    self.filename_ext = filename_ext
    self.workdir = workdir
    self.walk = walk

  def get_command(self):
    return "delete *%s in %s" % (self.filename_ext, self.workdir).split()

  def remove_ext_files(self):
    cwd=os.getcwd()
    if self.workdir is not None:
      if os.path.exists(self.workdir):
        os.chdir(self.workdir)
      else:
        return
    print "\n  removing %s files in %s, walk? %s" % (self.filename_ext,
                                                     os.getcwd(),
                                                     self.walk,
      )
    i=0
    if self.walk:
      for root, dirs, files in os.walk(".", topdown=False):
        for name in files:
          if name.endswith(self.filename_ext):
            os.remove(os.path.join(root, name))
            i+=1
    else:
      for name in os.listdir(os.getcwd()):
        if name.endswith(self.filename_ext):
          os.remove(os.path.join(name))
          i+=1
    os.chdir(cwd)
    print "  removed %d files" % i

  def run(self):
    self.remove_ext_files()

class cleanup_dirs(object):
  """Command to remove unwanted subdirectories"""

  def __init__(self, dirs, workdir=None):
    """
    :param dirs:    List of subdirectories to remove from workdir
    :param workdir: The root directory for everything in dirs. If None, then
                    the command will be run in the current working directory.
    """
    self.dirs = dirs
    self.workdir = workdir

  def get_command(self):
    return "cleanup dirs in %s" % (self.workdir).split()

  def remove_dirs(self):
    cwd=os.getcwd()
    try:
      # Move to the workdir
      if self.workdir is not None:
        if os.path.exists(self.workdir):
          os.chdir(self.workdir)
        else:
          return

      # Don't notify the user if we aren't doing anything
      if any(os.path.exists(d) for d in self.dirs):
        print "===== Removing directories in %s" % (os.getcwd())

        for d in self.dirs:
          if os.path.exists(d):
            print "      removing %s" % (os.path.join(os.getcwd(),d))
            shutil.rmtree(d)
    finally:
      # Leave the directory untouched even if we failed
      os.chdir(cwd)

  def run(self):
    self.remove_dirs()

##### Modules #####
class SourceModule(object):
  _modules = {}
  module = None
  authenticated = None
  authentarfile = None
  anonymous = None
  def __init__(self):
    if not self._modules:
      self.update_subclasses()

  def items(self):
    return self._modules.items()

  @classmethod
  def update_subclasses(cls):
    for i in cls.__subclasses__():
      cls._modules[i.module] = i

  def get_module(self, module):
    if module in self._modules:
      return self._modules[module]
    raise KeyError, "Unknown module: %s"%module

  def get_url(self, auth=None):
    repo = None
    try:
      repo = self.get_authenticated(auth=auth)
    except KeyError, e:
      repo = self.get_anonymous()
      if not repo:
        raise Exception('No anonymous access method defined for module: %s. Try with --%s'%(self.module, e.args[0]))
    repo = repo or self.get_anonymous()
    if not repo:
      raise Exception('No access method defined for module: %s'%self.module)
    return repo

  def get_authenticated(self, auth=None):
    auth = auth or {}
    if not self.authenticated:
      return None
    return [self.authenticated[0], self.authenticated[1]%auth]

  def get_tarauthenticated(self, auth=None):
    auth = auth or {}
    if self.authentarfile:
      return [self.authentarfile[0]%auth, self.authentarfile[1], self.authentarfile[2]]
    return None, None, None

  def get_anonymous(self):
    return self.anonymous

# Core external repositories
# The trailing slashes ARE significant.
# These must all provide anonymous access.
# On Windows due to absence of rsync we use pscp from the Putty programs.
class ccp4io_module(SourceModule):
  module = 'ccp4io'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/ccp4io.gz']
  authentarfile = ['%(cciuser)s@cci.lbl.gov', 'ccp4io.tar.gz', '/net/cci/auto_build/repositories/ccp4io']
  authenticated = ['rsync', '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/ccp4io/']

class annlib_module(SourceModule):
  module = 'annlib'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/annlib.gz']
  authentarfile = ['%(cciuser)s@cci.lbl.gov', 'annlib.tar.gz', '/net/cci/auto_build/repositories/annlib']
  authenticated = ['rsync', '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/annlib/']

class scons_module(SourceModule):
  module = 'scons'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/scons.gz']
  authentarfile = ['%(cciuser)s@cci.lbl.gov', 'scons.tar.gz', '/net/cci/auto_build/repositories/scons']
  authenticated = ['rsync', '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/scons/']

class boost_module(SourceModule):
  module = 'boost'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/boost.gz']
  # Compared to rsync pscp is very slow when downloading multiple files
  # Resort to downloading the compressed archive on Windows
  authentarfile = ['%(cciuser)s@cci.lbl.gov',
                   'boost_hot.tar.gz',
                   '/net/cci/auto_build/repositories/boost_hot/']
  authenticated = [
    'rsync',
    '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/boost_hot/']

# external modules
class amber_module(SourceModule):
  module = 'amber'
  # this doesn't work
  anonymous = ['curl', 'http://cci.lbl.gov/externals/AmberTools15.gz']
  # this doesn't work
  authentarfile = ['%(cciuser)s@cci.lbl.gov', 'AmberTools15.tar.gz', '/net/cci/auto_build/externals']
  authenticated = [
    'rsync',
    '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/externals/amber16/',
    'externals', # not mapped yet!
    'amber_rsync', # not plumbed ...
  ]
  #download downloader
  authenticated = [
    'scp',
    '%(cciuser)s@cci.lbl.gov:/net/cci-filer2/raid1/auto_build/externals/download_circleci_AmberTools.py']

class rosetta_class(SourceModule):
  module = 'rosetta'
  authenticated = [
    'rsync',
    '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/externals/'+rosetta_version_tar_bundle+'/',
  ]
  authenticated = [
    'scp',
    '%(cciuser)s@cci.lbl.gov:/net/cci-filer2/raid1/auto_build/externals/'+rosetta_version_tar_bundle+'.tgz']

class afitt_class(SourceModule):
  module = 'afitt'
  authenticated = [
    'scp',
    '%(cciuser)s@cci.lbl.gov:/net/cci-filer2/raid1/auto_build/externals/'+afitt_version+'.gz']

class libsvm_module(SourceModule):
  module = 'libsvm'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/libsvm.gz']
  authenticated = ['rsync', '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/libsvm/']

# Core CCTBX repositories
# These must all provide anonymous access.
class cctbx_module(SourceModule):
  module = 'cctbx_project'
  anonymous = ['git', '-b 2017B8085',
               'git@github.com:cctbx-xfel/cctbx_project.git',
               'https://github.com/cctbx-xfel/cctbx_project.git',
               'https://github.com/cctbx-xfel/cctbx_project/archive/2017B8085.zip']

class qrefine_module(SourceModule):
  module = 'qrefine'
  anonymous = ['git',
               'git@github.com:qrefine/qrefine.git',
               'https://github.com/qrefine/qrefine.git',
               #'git@github.com:cctbx/cctbx_project.git',
               #'https://github.com/cctbx/cctbx_project.git',
               #'https://github.com/cctbx/cctbx_project/archive/master.zip']
               ]

class mon_lib_module(SourceModule):
  module = 'mon_lib'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/mon_lib.gz']
  authentarfile = ['%(cciuser)s@cci.lbl.gov', 'mon_lib.tar.gz', '/net/cci/auto_build/repositories/mon_lib']
  #authenticated = ['rsync', '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/annlib/']

class geostd_module(SourceModule):
  module = 'geostd'
  anonymous = ['svn',
               'svn://svn.code.sf.net/p/geostd/code/trunk'
               ]
  authenticated = anonymous

class cbflib_module(SourceModule):
  module = 'cbflib'
  anonymous = ['git',
               'git@github.com:yayahjb/cbflib.git',
               'https://github.com/yayahjb/cbflib.git',
               'https://github.com/yayahjb/cbflib/archive/master.zip']

class ccp4io_adaptbx(SourceModule):
  module = 'ccp4io_adaptbx'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/ccp4io_adaptbx.gz']
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/ccp4io_adaptbx/trunk']

class annlib_adaptbx(SourceModule):
  module = 'annlib_adaptbx'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/annlib_adaptbx.gz']
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/annlib_adaptbx/trunk']

class tntbx_module(SourceModule):
  module = 'tntbx'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/tntbx.gz']
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/tntbx/trunk']

class clipper_module(SourceModule):
  module = 'clipper'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/clipper.gz']
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/clipper/trunk']

class gui_resources_module(SourceModule):
  module = 'gui_resources'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/gui_resources.gz']
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/gui_resources/trunk']

class opt_resources_module(SourceModule):
  module = 'opt_resources'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/opt_resources/trunk']

class eigen_module(SourceModule):
  module = 'eigen'
  anonymous = ['curl', 'http://cci.lbl.gov/repositories/eigen.gz']
  authentarfile = ['%(cciuser)s@cci.lbl.gov', 'eigen.tar.gz', '/net/cci/auto_build/repositories/eigen']
  authenticated = ['rsync', '%(cciuser)s@cci.lbl.gov:/net/cci/auto_build/repositories/eigen/']

# Phenix repositories
class phenix_module(SourceModule):
  module = 'phenix'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/phenix/trunk']

class phenix_html(SourceModule):
  module = 'phenix_html'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/phenix_html/trunk']

class phenix_examples(SourceModule):
  module = 'phenix_examples'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/phenix_examples/trunk']

class phenix_regression(SourceModule):
  module = 'phenix_regression'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/phenix_regression/trunk']

class plex_module(SourceModule):
  module = 'Plex'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/Plex/trunk']

class pyquante_module(SourceModule):
  module = 'PyQuante'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/PyQuante/trunk']

class chem_data_module(SourceModule):
  module = 'chem_data'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/chem_data/trunk']

class elbow_module(SourceModule):
  module = 'elbow'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/elbow/trunk']

class amber_adaptbx_module(SourceModule):
  module = 'amber_adaptbx'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/amber_adaptbx/trunk']

class ksdssp_module(SourceModule):
  module = 'ksdssp'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/ksdssp/trunk']

class pulchra_module(SourceModule):
  module = 'pulchra'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/pulchra/trunk']

class solve_resolve_module(SourceModule):
  module = 'solve_resolve'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/solve_resolve/trunk']

class reel_module(SourceModule):
  module = 'reel'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/reel/trunk']

class muscle_module(SourceModule):
  module = 'muscle'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/muscle/trunk']

class cxi_xdr_xes_module(SourceModule):
  module = 'cxi_xdr_xes'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/cxi_xdr_xes/trunk']

class buildbot_module(SourceModule):
  module = 'buildbot'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/buildbot/trunk']

# Phaser repositories
class phaser_module(SourceModule):
  module = 'phaser'
  anonymous = ['git',
               'git://git.uis.cam.ac.uk/cimr-phaser/phaser.git',
               'https://git.uis.cam.ac.uk/cimr-phaser/phaser.git']

class phaser_regression_module(SourceModule):
  module = 'phaser_regression'
  anonymous = ['git',
               'git://git.csx.cam.ac.uk/cimr-phaser/phaser_regression.git',
               'https://git.csx.cam.ac.uk/cimr-phaser/phaser_regression.git']

# DIALS repositories
class labelit_module(SourceModule):
  module = 'labelit'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/labelit/trunk']

class labelit_regression_module(SourceModule):
  module = 'labelit_regression'
  authenticated = ['svn', 'svn+ssh://%(cciuser)s@cci.lbl.gov/labelit_regression/trunk']

class dials_module(SourceModule):
  module = 'dials'
  anonymous = ['git',
               'git@github.com:dials/dials.git',
               'https://github.com/dials/dials.git',
               'https://github.com/dials/dials/archive/master.zip']

class dials_regression_module(SourceModule):
  module = 'dials_regression'
  authenticated = ['svn',
                   'svn+ssh://%(cciuser)s@cci.lbl.gov/dials_regression/trunk']

class xfel_regression_module(SourceModule):
  module = 'xfel_regression'
  authenticated = ['svn',
                   'svn+ssh://%(cciuser)s@cci.lbl.gov/xfel_regression/trunk']

class xia2_module(SourceModule):
  module = 'xia2'
  anonymous = ['git',
               'git@github.com:xia2/xia2.git',
               'https://github.com/xia2/xia2.git',
               'https://github.com/xia2/xia2/archive/master.zip']

class xia2_regression_module(SourceModule):
  module = 'xia2_regression'
  anonymous = ['git',
               'git@github.com:xia2/xia2_regression.git',
               'https://github.com/xia2/xia2_regression.git',
               'https://github.com/xia2/xia2_regression/archive/master.zip']

# Duke repositories
class probe_module(SourceModule):
  module = 'probe'
  anonymous = ['svn', 'https://github.com/rlabduke/probe.git/trunk']

class suitename_module(SourceModule):
  module = 'suitename'
  anonymous = ['svn', 'https://github.com/rlabduke/suitename.git/trunk']

class reduce_module(SourceModule):
  module = 'reduce'
  anonymous = ['svn', 'https://github.com/rlabduke/reduce.git/trunk']

class king_module(SourceModule):
  module = 'king'
  anonymous = ['svn',
               'https://github.com/rlabduke/phenix_king_binaries.git/trunk']

class molprobity_moodule(SourceModule):
  module = 'molprobity'
  anonymous = ['svn', 'https://github.com/rlabduke/MolProbity.git/trunk']

MODULES = SourceModule()

###################################
##### Base Configuration      #####
###################################

class Builder(object):
  """Create buildbot configurations for CCI and CCTBX-like software."""
  # Base packages
  BASE_PACKAGES = 'all'
  # Checkout these codebases
  CODEBASES = ['cctbx_project']
  CODEBASES_EXTRA = []
  # Copy these sources from cci.lbl.gov
  HOT = []
  HOT_EXTRA = []
  # Configure for these cctbx packages
  LIBTBX = ['cctbx']
  LIBTBX_EXTRA = []

  def __init__(
      self,
      category=None,
      subcategory=None,
      platform=None,
      sep=None,
      python_base=None,
      cleanup=False,
      hot=True,
      update=True,
      revert=None,
      base=True,
      build=True,
      tests=True,
      doc=True,
      distribute=False,
      auth=None,
      with_python=None,
      nproc=1,
      verbose=False,
      download_only=False,
      skip_base="",
      force_base_build=False,
      enable_shared=False,
    ):
    if nproc is None:
      self.nproc=1
    else:
      self.nproc=nproc
    """Create and add all the steps."""
    # self.cciuser = cciuser or getpass.getuser()
    self.set_auth(auth)
    self.steps = []
    self.category = category
    self.subcategory = subcategory
    if self.subcategory: self.EXTERNAL_CODEBASES = [self.subcategory]
    self.platform = platform
    if self.isPlatformWindows():
      self.op = ntpath
    else:
      self.op = os.path
    self.name = '%s-%s'%(self.category, self.platform)
    # Platform configuration.
    self.python_base = self.opjoin(*['..', 'base', 'bin', 'python'])
    if self.platform and 'windows' in self.platform:
      self.python_base = self.opjoin(*['..', 'base', 'bin', 'python', 'python.exe'])
    if sys.platform == "win32": # assuming we run standalone without buildbot
      self.python_base = self.opjoin(*[os.getcwd(), 'base', 'bin', 'python', 'python.exe'])
    self.with_python = with_python
    if self.with_python:
      self.python_base = with_python
    self.verbose = verbose
    self.download_only = download_only
    self.skip_base = skip_base
    self.force_base_build = force_base_build
    self.add_init()

    # Cleanup
    if cleanup:
      self.cleanup(['dist', 'tests', 'doc', 'tmp', 'base', 'base_tmp', 'build'])
    else:
      self.cleanup(['dist', 'tests', 'tmp'])

    if self.platform and 'windows' in self.platform: # only executed by buildbot master
      from buildbot.steps.transfer import FileDownload
      # download us to folder above modules on slave so we can run the utility functions defined above
      self.add_step(FileDownload(mastersrc="bootstrap.py", slavedest="../bootstrap.py"))

    # Add 'hot' sources
    if hot:
      map(self.add_module, self.get_hot())

    # Add svn sources.
    self.revert=revert
    if update:
      map(self.add_module, self.get_codebases())

    # always remove .pyc files
    self.remove_pyc()

    # Build base packages
    if base:
      extra_opts = ["--nproc=%s" % str(self.nproc)]
      if enable_shared:
        extra_opts.append("--python-shared")
      self.add_base(extra_opts=extra_opts)

    # Configure, make, get revision numbers
    if build and not self.download_only:
      self.add_configure()
      self.add_make()
      self.add_install()

    # Tests, tests
    if tests and not self.download_only:
      self.add_tests()

    # docs
    if doc:
      self.rebuild_docs()

    # Distribute
    if distribute and not self.download_only:
      self.add_distribute()

    # Distribute does this but uses correct PHENIX_VERSION
    if build and not self.download_only:
      self.add_dispatchers()
      self.add_refresh()

    if self.platform and 'windows' in self.platform: # only executed by buildbot master
      self.add_rm_bootstrap_on_slave()

  def isPlatformWindows(self):
    if self.platform and 'windows' in self.platform:
        return True
    else:
      if self.platform == "dev" and sys.platform == "win32":
        return True
    return False

  def isPlatformLinux(self):
    if self.platform and 'linux' in self.platform:
        return True
    else:
      if self.platform == "dev" and sys.platform.startswith("linux"):
        return True
    return False

  def isPlatformMacOSX(self):
    if self.platform and 'mac' in self.platform:
        return True
    else:
      if self.platform == "dev" and sys.platform.startswith("darwin"):
        return True
    return False

  def add_auth(self, account, username):
    self.auth[account] = username

  def set_auth(self, auth):
    self.auth = auth or {}

  def get_auth(self):
    return self.auth

  def remove_pyc(self):
    self.add_step(cleanup_ext_class(".pyc", "modules"))

  def shell(self, **kwargs):
    # Convenience for ShellCommand
    kwargs['haltOnFailure'] = kwargs.pop('haltOnFailure', True)
    kwargs['description'] = kwargs.get('description') or kwargs.get('name')
    kwargs['timeout'] = 60*60*2 # 2 hours
    if 'workdir' in kwargs:
      kwargs['workdir'] = self.opjoin(*kwargs['workdir'])
    return ShellCommand(**kwargs)

  def run(self):
    for i in self.steps:
      i.run()

  def opjoin(self, *args):
    return self.op.join(*args)

  def get_codebases(self):
    if self.isPlatformWindows():
      rc = set(self.CODEBASES+self.CODEBASES_EXTRA)
      for r in windows_remove_list: rc = rc - set([r])
      return list(rc)
    rc = self.CODEBASES + self.CODEBASES_EXTRA
    if hasattr(self, "EXTERNAL_CODEBASES"):
      rc = self.EXTERNAL_CODEBASES + rc
    return rc

  def get_hot(self):
    return self.HOT + self.HOT_EXTRA

  def get_libtbx_configure(self): # modified in derived class PhenixBuilder
    return self.LIBTBX + self.LIBTBX_EXTRA

  def add_init(self):
    pass

  def cleanup(self, dirs=None):
    dirs = dirs or []
    if self.isPlatformWindows():
      # deleting folders by copying an empty folder with robocopy is more reliable on Windows
      cmd=['cmd', '/c', 'mkdir', 'empty', '&', '(FOR', '%d', 'IN', '('] + dirs + \
       [')', 'DO', '(ROBOCOPY', 'empty', '%d', '/MIR', '>', 'nul', '&', 'rmdir', '%d))', '&', 'rmdir', 'empty']
      self.add_step(self.shell(
        name='Removing directories ' + ', '.join(dirs),
        command =cmd,
        workdir=['.'],
        description="deleting " + ", ".join(dirs),
      ))
    else:
      self.add_step(cleanup_dirs(dirs, "modules"))

  def add_rm_bootstrap_on_slave(self):
    # if file is not found error flag is set. Mask it with cmd shell
    cmd=['cmd', '/c', 'del', '/Q', "bootstrap.py*", '&', 'set', 'ERRORLEVEL=0']
    self.add_step(self.shell(
      name='removing bootstrap utilities',
      command =cmd,
      workdir=['.'],
      description="remove temporary bootstrap.py*",
    ))

  def add_step(self, step):
    """Add a step."""
    self.steps.append(step)
    if 0:
      print "commands "*8
      for step in self.steps:
        print step
        #try:    print " ".join(step.get_command())
        #except: print '????'
      print "commands "*8

  def add_module(self, module, workdir=None, module_directory=None):
    action = MODULES.get_module(module)().get_url(auth=self.get_auth())
    method, parameters = action[0], action[1:]
    if len(parameters) == 1: parameters = parameters[0]
    tarurl, arxname, dirpath = None, None, None
    if self.isPlatformWindows() and (method == "authenticated" or method == "rsync"):
      tarurl, arxname, dirpath = MODULES.get_module(module)().get_tarauthenticated(auth=self.get_auth())
    if self.isPlatformWindows():
      if module in windows_remove_list:
        return
    if method == 'rsync' and not self.isPlatformWindows():
      self._add_rsync(module,
                      parameters, # really the url
                      workdir=workdir,
                      module_directory=module_directory)
    elif self.isPlatformWindows() and tarurl:
      # if more bootstraps are running avoid potential race condition on
      # remote server by using unique random filenames
      randarxname = next(tempfile._get_candidate_names()) + "_" + arxname
      self._add_remote_make_tar(module, tarurl, randarxname, dirpath)
      self._add_scp(module, tarurl + ':' + randarxname)
      self._add_remote_rm_tar(module, tarurl, randarxname)
    elif method == 'scp':
      self._add_scp(module, parameters)
    elif method == 'curl':
      self._add_curl(module, parameters)
    elif method == 'svn':
      self._add_svn(module, parameters)
    elif method == 'git':
      self._add_git(module, parameters)
    else:
      raise Exception('Unknown access method: %s %s'%(method, str(parameters)))

  def _add_rsync(self, module, url, workdir=None, module_directory=None):
    """Add packages not in source control."""
    # rsync the hot packages.
    if not workdir: workdir=["modules"]
    if not module_directory: module_directory=module
    self.add_step(self.shell(
      name='hot %s'%module,
      command=[
        'rsync',
        '-rptgoDLK', #'-aL',
        '--delete',
        url,
        module_directory,
      ],
      workdir=workdir,
    ))

  def _add_remote_make_tar(self, module, tarurl, arxname, dirpath):
    """Windows: tar up hot packages for quick file transfer since there's no rsync and pscp is painfully slow"""
    if dirpath[-1] == '/':
      dirpath = dirpath[:-1]
    basename = posixpath.basename(dirpath)
    cmd=[
        'ssh',
        tarurl,
        '"' + 'cd',
        posixpath.split(dirpath)[0],
        '&&',
        'tar',
        'cfzh',
        '~/' + arxname,
        basename + '"'
      ]
    mstr= " ".join(cmd)
    self.add_step(self.shell( # pack directory with tar on remote system
      name='hot %s'%module,
      command=mstr,
      workdir=['modules'],
      description="create remote temporary archive %s:%s" %(tarurl, arxname),
    ))

  def _add_remote_rm_tar(self, module, tarurl, arxname):
    """Windows: Delete tar file on remote system, unpack tar file locally, then delete tar file locally"""
    self.add_step(self.shell( # delete the tarfile on remote system
      name='hot %s'%module,
      command=[
        'ssh',
        tarurl,
        'rm ',
        arxname
      ],
      workdir=['modules'],
      description="delete remote temporary archive of %s" %module,
    ))
    self.add_step(self.shell(command=[
      "python","-c","import sys; sys.path.append('..'); import bootstrap; \
      bootstrap.tar_extract('','%s', '%s')" %(arxname, module) ],
      workdir=['modules'],
      description="extracting archive files to %s" %module,
    ))
    self.add_step(self.shell( # delete the tarfile locally
      # use 'cmd', '/c' as a substitute for shell=True in the subprocess.Popen call
      command=['cmd', '/c', 'del', arxname],
      workdir=['modules'],
      description="delete local temporary archive of %s" %module,
    ))

  def _add_scp(self, module, url):
    self.add_step(self.shell(
      name='hot %s'%module,
      command=[
        'scp',
        '-r',
        url,
        '.',
      ],
      workdir=['modules'],
      description="getting remote file %s" %url.split("/")[-1],
    ))

  def _add_download(self, url, to_file):
    class _download(object):
      def run(self):
        print "===== Downloading %s: " % url,
        Toolbox().download_to_file(url, to_file)
    self.add_step(_download())

  def _add_curl(self, module, url):
    filename = urlparse.urlparse(url)[2].split('/')[-1]
    self._add_download(url, os.path.join('modules', filename))
    self.add_step(self.shell(
      name="extracting files from %s" %filename,
      command=[
       "python","-c","import sys; sys.path.append('..'); import bootstrap; \
       bootstrap.tar_extract('','%s')" %filename],
      workdir=['modules'],
      description="extracting files from %s" %filename,
    ))

  def _add_unzip(self, archive, directory, trim_directory=0):
    class _indirection(object):
      def run(self):
        print "===== Installing %s into %s" % (archive, directory)
        Toolbox().unzip(archive, directory, trim_directory)
    self.add_step(_indirection())

  def _add_svn(self, module, url):
    update_list = ['update']
    if module in ["reduce", "probe", "king", "suitename"]:
      pass
    elif self.revert:
      update_list = ['update', '-r', self.revert]
    thisworkdir = 'modules'
    if module == 'molprobity' : thisworkdir = '.'
    # avoid stalling bootstrap with prompts
    # or when encountering unknown server certificates
    svnflags = ['--non-interactive', '--trust-server-cert']
    if os.path.exists(self.opjoin(*[thisworkdir, module, '.svn'])):
      self.add_step(self.shell(
          command=['svn'] + update_list +[module] + svnflags,
          workdir=[thisworkdir]
      ))
      self.add_step(self.shell(
          command=['svn', 'status', module] + svnflags,
          workdir=[thisworkdir],
          quiet=True,
      ))
    elif os.path.exists(self.opjoin(*[thisworkdir, module])):
      print "Existing non-svn directory -- don't know what to do. skipping: %s"%module
    else:
      # print "fresh checkout..."
      self.add_step(self.shell(
          command=['svn', 'co', url, module] + svnflags,
          workdir=[thisworkdir]
      ))

  def _add_git(self, module, parameters, destination=None):
    use_git_ssh = self.auth.get('git_ssh', False)
    reference_repository_path = self.auth.get('git_reference', None)
    if reference_repository_path is None:
      if os.name == 'posix' and 'diamond.ac.uk' in pysocket.gethostname():
        reference_repository_path = '/dls/science/groups/scisoft/DIALS/repositories/git-reference'
    if reference_repository_path is not None:
      reference_repository_path = os.path.join(reference_repository_path, module)
    class _indirection(object):
      def run(self):
        Toolbox().git(module, parameters, destination=destination,
            use_ssh=use_git_ssh, verbose=True, reference=reference_repository_path)
    self.add_step(_indirection())

  def _check_for_Windows_prerequisites(self):
    if self.isPlatformWindows():
      # platform specific checks cannot run on buildbot master so add to build steps to run on slaves
      self.add_step(self.shell(command=[
         "python","-c","import sys; sys.path.append('..'); import bootstrap; \
          bootstrap.CheckWindowsPrerequisites()"],
        workdir=['modules'],
        description="Checking Windows prerequisites",
      ))

  def add_command(self, command, name=None, workdir=None, args=None, **kwargs):
    if self.isPlatformWindows():
      command = command + '.bat'
    # Relative path to workdir.
    workdir = workdir or ['build']
    dots = [".."]*len(workdir)
    if workdir[0] == '.':
      dots = []
    if sys.platform == "win32": # assuming we run standalone without buildbot
      dots.extend([os.getcwd(), 'build', 'bin', command])
    else:
      dots.extend(['build', 'bin', command])
    self.add_step(self.shell(
      name=name or command,
      command=[self.opjoin(*dots)] + (args or []),
      workdir=workdir,
      **kwargs
    ))

  def add_test_command(self,
                       command,
                       name=None,
                       workdir=None,
                       args=None,
                       haltOnFailure=False,
                       **kwargs
                       ):
    if name is None: name='test %s'%command
    self.add_command(
      command,
      name=name,
      workdir=(workdir or ['tests', command]),
      args=args,
      haltOnFailure=haltOnFailure,
      **kwargs
    )

  def add_test_parallel(self, module=None, nproc=None, **kwargs):
    if nproc is None:
      nprocstr = 'nproc=auto'
    else:
      nprocstr = 'nproc=%d'%nproc
    self.add_command(
      'libtbx.run_tests_parallel',
      name='test %s'%module,
      workdir=['tests', module],
      args=['module=%s'%module, nprocstr, 'verbosity=1'],
      haltOnFailure=False,
      **kwargs
    )

  def add_refresh(self):
    self.add_command(
      'libtbx.refresh',
      name='libtbx.refresh',
      workdir=['.'],
    )

  # Override these methods.
  def add_base(self, extra_opts=[]):
    """Build the base dependencies, e.g. Python, HDF5, etc."""
    if self.with_python:
      extra_opts = ['--with-python', self.with_python]
    if self.verbose:
      extra_opts.append('-v')
    if self.download_only:
      extra_opts.append('--download-only')
    if self.auth.get('git_ssh',False):
      extra_opts.append('--git-ssh')
    if self.skip_base:
      extra_opts.append('--skip-base=%s' % self.skip_base)
    if not self.force_base_build:
      if "--skip-if-exists" not in extra_opts:
        extra_opts.append("--skip-if-exists")
    self.add_step(self.shell(
      name='base',
      command=[
        'python',
        self.opjoin('modules', 'cctbx_project', 'libtbx', 'auto_build', 'install_base_packages.py'),
        '--python-shared',
        '--%s'%self.BASE_PACKAGES
      ] + extra_opts,
      workdir=['.']
    ))

  def add_dispatchers(self, product_name="phenix"):
    """Write dispatcher_include file."""
    """Generating Phenix environment additions for dispatchers..."""
    envcmd = "export"
    dispatcher = os.path.join("build",
                              "dispatcher_include_%s.sh" %
                              product_name)
    if self.isPlatformWindows():
      envcmd = "set"
      dispatcher = os.path.join("build",
                                "dispatcher_include_%s.bat" %
                                product_name)
    if (os.path.isfile(dispatcher)): os.remove(dispatcher)
    env_prefix = product_name.upper() # e.g. "Phenix" -> "PHENIX"
    prologue = "\n".join([
      "%s %s=\"%s\"" % (envcmd, env_prefix, os.getcwd()),
      "%s %s_VERSION=%s" % (envcmd, env_prefix, "dev-svn"),
      "%s %s_ENVIRONMENT=1" % (envcmd, env_prefix),
      #"%s %s_MTYPE=%s" % (envcmd, env_prefix, "none"),
    ] #+ self.product_specific_dispatcher_prologue())
                           )
    #epilogue = "\n".join(self.product_specific_dispatcher_epilogue())
    dispatcher_opts = [
      "--build_dir=%s" % ".",
      "--base_dir=%s"  % "../base",
      "--suffix=%s"    % "phenix",
      "--gtk_version=2.10.0", # XXX this can change!
      #"--quiet",
    ]
    #if (not self.flag_build_gui) :
    #  dispatcher_opts.append("--ignore_missing_dirs")
    # FIXME this will happen regardless of whether the GUI modules are being
    # distributed or not - will this be problematic?
    self.add_step(self.shell(
      name='gui dispatcher',
      command=[
        self.python_base, #'python',
        self.opjoin("..",
                    'modules',
                    'cctbx_project',
                    'libtbx',
                    'auto_build',
                    'write_gui_dispatcher_include.py'),
        '--prologue=%s' % prologue,
        #"--epilogue=%s"
      ] + dispatcher_opts,
      workdir=['build']
    ))

  def add_configure(self):
    self.add_step(self.shell(command=[
        self.python_base, # default to using our python rather than system python
        self.opjoin('..', 'modules', 'cctbx_project', 'libtbx', 'configure.py')
        ] + self.get_libtbx_configure(),
      workdir=['build'],
      description="run configure.py",
    ))
    # Prepare saving configure.py command to file should user want to manually recompile Phenix
    configcmd =[
        self.python_base, # default to using our python rather than system python
        self.opjoin('..', 'modules', 'cctbx_project', 'libtbx', 'configure.py')
        ] + self.get_libtbx_configure()
    fname = self.opjoin("config_modules.cmd")
    ldlibpath = ''
    if self.isPlatformLinux():
      ldlibpath = 'export LD_LIBRARY_PATH=../base/lib\n'
      # because that was the environment when python and base components were built during bootstrap
    confstr = ldlibpath + subprocess.list2cmdline(configcmd)
    if not self.isPlatformWindows():
      fname = self.opjoin("config_modules.sh")
      confstr = '#!/bin/sh\n\n' + confstr
    # klonky way of writing file later on, but it works
    self.add_step(self.shell(command=[
         'python','-c','open(r\"%s\",\"w\").write(r\"\"\"%s\"\"\" + \"\\n\")' %(fname, confstr)
         ],
      workdir=['build'],
      description="save configure command",
    ))
    if not self.isPlatformWindows():
      self.add_step(self.shell(command=[ 'chmod', '+x', fname ],
        workdir=['build'],
        description="permit execution of config_modules.sh",
      ))

  def add_make(self):
    self.add_command('libtbx.scons', args=['-j',
                                           str(self.nproc),
#                                          #"--skip-version", # for Phaser
                                           ])

  def add_install(self):
    """Run after compile, before tests."""
    self.add_command('mmtbx.rebuild_rotarama_cache',
                     name="rebuild rotarama",
    )

  def add_tests(self):
    """Run the unit tests."""
    pass

  def rebuild_docs(self):
    self.add_command('phenix_html.rebuild_docs')

  def add_distribute(self):
    pass

##### Specific Configurations ######

class CCIBuilder(Builder):
  """Base class for packages that include CCTBX as a dependency."""
  # Base packages
  BASE_PACKAGES = 'all'
  # Checkout these codebases
  CODEBASES = [
    'cbflib',
    'cctbx_project',
    'gui_resources',
    'ccp4io_adaptbx',
    'annlib_adaptbx',
    'tntbx',
    'clipper'
  ]
  CODEBASES_EXTRA = []
  # Copy these sources from cci.lbl.gov
  HOT = [
    'annlib',
    'boost',
    'scons',
    'ccp4io',
    'eigen',
    #"libsvm",
  ]
  HOT_EXTRA = []
  # Configure for these cctbx packages
  LIBTBX = [
    'cctbx',
    'cbflib',
    'scitbx',
    'libtbx',
    'iotbx',
    'mmtbx',
    'smtbx',
    'dxtbx',
    'gltbx',
    'wxtbx',
  ]
  LIBTBX_EXTRA = []

##### CCTBX-derived packages #####

class MOLPROBITYBuilder(Builder):
  BASE_PACKAGES = 'molprobity'
  # Checkout these codebases
  CODEBASES = [
    'cbflib',
    'cctbx_project',
    'ccp4io_adaptbx',
    'annlib_adaptbx',
    'tntbx',
  ]
  CODEBASES_EXTRA = [
    'molprobity',
    'chem_data',
    'reduce',
    'probe',
    'suitename'
  ]
  # Copy these sources from cci.lbl.gov
  HOT = [
    'annlib',
    'boost',
    'scons',
    'ccp4io',
    #"libsvm",
  ]
  HOT_EXTRA = []
  # Configure for these cctbx packages
  LIBTBX = [
    'mmtbx',
  ]
  LIBTBX_EXTRA = [
  ]

  def add_tests(self):
    pass

# def add_base(self, extra_opts=[]):
#   super(MOLPROBITYBuilder, self).add_base(
#     extra_opts=['--molprobity',
#                ] + extra_opts)

  def add_dispatchers(self):
    pass

  def rebuild_docs(self):
    pass

class CCTBXBuilder(CCIBuilder):
  BASE_PACKAGES = 'cctbx'
  def add_tests(self):
    self.add_test_command('libtbx.import_all_python', workdir=['modules', 'cctbx_project'])
    self.add_test_command('cctbx_regression.test_nightly')

  def add_base(self, extra_opts=[]):
    super(CCTBXBuilder, self).add_base(
      extra_opts=['--cctbx',
                 ] + extra_opts)

  def add_dispatchers(self):
    pass

  def rebuild_docs(self):
    pass

class DIALSBuilder(CCIBuilder):
  CODEBASES_EXTRA = ['dials', 'xia2']
  LIBTBX_EXTRA = ['dials', 'xia2', 'prime', 'iota', '--skip_phenix_dispatchers']
  def add_tests(self):
    self.add_test_command('cctbx_regression.test_nightly')
    self.add_test_parallel('dials', flunkOnFailure=False, warnOnFailure=True)

  def add_base(self, extra_opts=[]):
    super(DIALSBuilder, self).add_base(
      extra_opts=['--dials',
                  #'--wxpython3'
                 ] + extra_opts)

  def add_dispatchers(self):
    pass

  def rebuild_docs(self):
    pass

class LABELITBuilder(CCIBuilder):
  CODEBASES_EXTRA = ['labelit']
  LIBTBX_EXTRA = ['labelit']

  def add_base(self, extra_opts=[]):
    super(LABELITBuilder, self).add_base(
      extra_opts=['--labelit'] + extra_opts)

  def add_tests(self):
    self.add_test_parallel('labelit', flunkOnFailure=False, warnOnFailure=True)

  def add_dispatchers(self):
    pass

  def rebuild_docs(self):
    pass

class XFELBuilder(CCIBuilder):
  CODEBASES_EXTRA = [
    'dials',
    'labelit',
    'cxi_xdr_xes'
  ]
  LIBTBX_EXTRA = [
    'dials',
    'labelit',
    'xfel',
    'cxi_xdr_xes',
    'prime',
    'iota'
  ]

  def add_base(self, extra_opts=[]):
    super(XFELBuilder, self).add_base(
      extra_opts=['--labelit'] + extra_opts)

  def add_tests(self):
    self.add_test_command('cctbx_regression.test_nightly')

  def add_dispatchers(self):
    pass

  def rebuild_docs(self):
    pass

class PhenixBuilder(CCIBuilder):
  CODEBASES_EXTRA = [
    'chem_data',
    'phenix',
    'phenix_regression',
    'phenix_html',
    'phenix_examples',
    'labelit',
    'Plex',
    'PyQuante',
    'elbow',
    'amber_adaptbx',
    'ksdssp',
    'pulchra',
    'solve_resolve',
    'reel',
    'gui_resources',
    'opt_resources',
    'muscle',
    'reduce',
    'probe',
    'king',
    'suitename',
    'dials',
    'xia2',
    'phaser',
    'phaser_regression',
  ]
  HOT_EXTRA = [
  ]
  LIBTBX_EXTRA = [
    'chem_data',
    'phenix',
    'phenix_regression',
    'phenix_examples',
    'solve_resolve',
    'reel',
    'phaser',
    'phaser_regression',
    'labelit',
    'elbow',
    'amber_adaptbx',
    'reduce',
    'probe',
    'dials',
    'xia2',
    'prime',
    'iota',
  ]

  def add_base(self, extra_opts=[]):
    super(PhenixBuilder, self).add_base(
      extra_opts=['--phenix',
                  '--labelit',
                  '--dials'
                 ] + extra_opts)

  def add_install(self):
    Builder.add_install(self)
    #self.rebuild_docs()


  def get_libtbx_configure(self):
    configlst = super(PhenixBuilder, self).get_libtbx_configure()
    if not self.isPlatformMacOSX():
      configlst.append("--enable_openmp_if_possible=True")
    #if self.isPlatformMacOSX():
    #  configlst.append("--compiler=clang-omp")
    return configlst


  def rebuild_docs(self):
    self.add_command('phenix_html.rebuild_docs')

  def add_tests(self):
    # Include cctbx tests.
    self.add_test_command('libtbx.import_all_ext')
    self.add_test_command('cctbx_regression.test_nightly')
    # Windows convenience hack.
    if self.isPlatformWindows():
      self.add_test_command('phenix_regression.test_nightly_windows')
    else:
      self.add_test_command('phenix_regression.test_nightly')
    # Other Phenix tests.
    self.add_test_parallel(module='elbow')
    self.rebuild_docs()
    self.add_test_command('phenix_regression.run_p9_sad_benchmark',
                          name="test p9 sad",
                         )
    self.add_test_command('phenix_regression.run_hipip_refine_benchmark',
                          name="test hipip",
                         )
    self.add_test_command('phenix_regression.wizards.test_all_parallel',
      args = ['nproc=8'],
      name="test wizards",
                         )
    run_dials_tests=True
    if self.isPlatformWindows():
      if 'dials' in windows_remove_list:
        run_dials_tests=False
    if run_dials_tests:
      self.add_test_parallel('dials', flunkOnFailure=False, warnOnFailure=True)

class PhenixExternalRegression(PhenixBuilder):
  EXTERNAL_CODEBASES = [
    "afitt",
    "rosetta",
    "amber",
    ]

  def cleanup(self, dirs=None):
    self.add_step(cleanup_ext_class(".bz2", "modules", walk=False))
    lt = time.localtime()
    cleaning = ['dist', 'tests', 'doc', 'tmp', 'base_tmp']
    if lt.tm_wday==5: # do a completer build on Saturday night
      cleaning += ['base', 'base_tmp', 'build']
    # Preparation
    # AFITT
    if self.subcategory in [None, "afitt"]:
      self.add_step(cleanup_dirs(['openeye'], 'modules'))
    # Amber
    if self.subcategory in [None, "amber"]:
      self.add_step(cleanup_dirs(['amber18'], 'modules'))
      self.add_step(cleanup_dirs(['amber17'], 'modules'))
      self.add_step(cleanup_dirs(['amber16'], 'modules'))
    PhenixBuilder.cleanup(self, cleaning)

  def get_environment(self, add_build_python_to_path=True):
    #  "AMBERHOME"           : amberhome, # used to trigger Property on slave
    environment = {}
    for env, dirs in envs.items():
      environment[env] = os.path.join(*dirs)
    if add_build_python_to_path:
      old_path = os.environ.get("PATH", "") # this is just another now
                                            # universal hack to get Amber to
                                            # compile...
      environment["PATH"] = '%s:%s' % (os.path.join(#os.getcwd(),
                                                    "build",
                                                    "bin",
                                                  ),
                                       old_path,
                                       )
    return environment

  def write_environment(self,
                        env,
                        filename="setpaths_externals",
                       ):
    # called by add_make which is called in build
    # this is a little funky as it seems to be very often in the wrong remote dir
    outl = ""
    for key, path in env.items():
      if key in ["PATH"]: continue
      outl += 'setenv %(key)s "%%(PWD)s/../%(path)s"\n' % locals()
    fname="%s.csh" % filename
    self.add_step(self.shell(command=[
      'python',
      '-c',
      'import os; open("%s","w").write("""%s""" %% os.environ)' %(fname, outl)
      ],
      workdir=['build'],
      description="save csh external paths",
    ))
    outl = ""
    for key, path in env.items():
      if key in ["PATH"]: continue
      outl += 'export %(key)s="%%(PWD)s/../%(path)s"\n' % locals()
    fname="%s.sh" % filename
    self.add_step(self.shell(command=[
      'python',
      '-c',
      'import os; open("%s","w").write("""%s""" %% os.environ)' %(fname, outl)
      ],
      workdir=['build'],
      description="save sh external paths",
    ))

  def add_make(self):
    # Phenix compile
    PhenixBuilder.add_make(self)
    # need to use the Phenix python for building
    # Amber
    # Rosetta
    # AFITT
    env = self.get_environment()
    self.write_environment(env)
    # not universal but works because only slave running this is same as master
    amber_c_comp = "clang"
    if sys.platform == "linux2":
      amber_c_comp = "gnu"
    for name, command, workdir in [
        ['AFITT - untar',
         ['tar', 'xvf', '%s.gz' % afitt_version],
         ['modules']],
        ['Amber pip requests', [self.python_base,
                                '-m',
                                'pip',
                                'install',
                                'requests',
                                ],
         ['modules']],
        ['Amber download bzip2',
         [self.python_base, #'python',
          'download_circleci_AmberTools.py',
          '--exclude-conda',
          '--local-file-name',
          '%s.tar.bz2' % amber_version,
          ],
         ['modules'],
        ],
        ['Amber bzip2 -d',
         ['bzip2', '-d', '-f', '%s.tar.bz2' % amber_version],
         ['modules'],
          ],
        ['Amber - untar',
         ['tar', 'xvf', '%s.tar' % amber_version],
         ['modules'],
          ],
        ['Amber - rm link',
         # not windows compatible
         ['rm', '-f', "amber"],
         ['modules']],
        ['Amber - link',
         # not windows compatible
         ['ln', '-sf', '%s' % amber_dir, "amber"],
         ['modules']],
        #['Amber update', ["./update_amber", "--update"], [env["AMBERHOME"]]],
        #['Amber configure',
        #  ["./configure",
        #   "--no-updates",
        #   "-noX11",
        #   "-macAccelerate", # ignored if not on Mac
        #   "-nofftw3", # because compilers on slave are 4.1 not 4.3
        #   #"-noamber", # this is for the "real" amber
        #   amber_c_comp,
        #   ],
        #  [env["AMBERHOME"]]],
        #['Amber compile',
        # ["make", "-j", self.nproc, "install"],
        # [env["AMBERHOME"]]],
        #['Amber clean',   ["make", "clean"], [env["AMBERHOME"]]],
        ['Rosetta - untar',
         ['tar', 'xvf', '%s.tgz' % rosetta_version_tar_bundle],
         ['modules']],
        ['Rosetta - rm link',
         # not windows compatible
         ['rm', '-f', "rosetta"],
         ['modules']],
        ['Rosetta - link',
         # not windows compatible
         ['ln', '-sf', '%s' % rosetta_version_directory, "rosetta"],
         ['modules']],
        #['Rosetta compile', # not really needed
        # ["./scons.py",
        #  "-j",
        #  self.nproc,
        #  #"mode=release",
        # ],
        # ["modules", 'rosetta', "main", "source"]],
        ]:
      if self.subcategory:
        if name.lower().find(self.subcategory)==-1: continue
      haltOnFailure=True
    #  if name.lower().find('amber')>-1:
    #    haltOnFailure=False
      self.add_step(self.shell(
        name       = name,
        command    = command,
        workdir    = workdir,
        description= "",
        env        = env,
        haltOnFailure = haltOnFailure,
        ))

    self.add_refresh()
    # Amber
    if self.subcategory in [None, "amber"]:
      self.add_command(
        'phenix.build_amber_interface',
        name='phenix.build_amber_interface',
        workdir=['.'],
        env=env,
        haltOnFailure=False,
      )
    # Rosetta
    if self.subcategory in [None, "rosetta"]:
      self.add_command(
        'rosetta.build_phenix_interface',
        args = ["nproc=%s" % self.nproc],
        name='rosetta.build_phenix_interface',
        workdir=['.'],
        env=env,
      )

  def add_tests(self):
    # amber
    if self.subcategory in [None, "amber"]:
      self.add_test_command('amber.run_tests',
                            env = self.get_environment(),
                            haltOnFailure=False,
                           )
    # rosetta refine
    if self.subcategory in [None, "rosetta"]:
      self.add_test_command('rosetta.run_tests',
                            env = self.get_environment()
                           )
    # MR rosetta
    if self.subcategory in [None, "rosetta"]:
      self.add_test_command(
        'phenix_regression.wizards.run_wizard_test',
        args=['test_prerefine'],
        name="test MR rosetta quick",
        env = self.get_environment()
      )
    # afitt
    if self.subcategory in [None, "afitt"]:
      self.add_test_command('afitt.run_tests',
                            env = self.get_environment()
                           )
    # erraser
    if self.subcategory in [None, "rosetta"]:
      self.add_test_command('erraser.run_tests',
                            env = self.get_environment()
                           )

class QRBuilder(PhenixBuilder):
  #
  # Designed to be run in Phenix build to add Q|R
  # and the entire PhenixBuilder if user is builder
  #
  EXTERNAL_CODEBASES = ["qrefine"]
  user = os.environ.get('USER', None)

  def add_make(self):
    if self.user=='builder': PhenixBuilder.add_make(self)
    pip_installs = ['ase', 'JPype1','pymongo']
    instructions = []
    for pi in pip_installs:
      instructions.append(['Q|R pip %s' % pi,
                           [self.python_base,
                            '-m',
                            'pip',
                            'install',
                            pi
                          ],
                           ['modules']])

    for name, command, workdir in instructions:
      self.add_step(self.shell(
        name       = name,
        command    = command,
        workdir    = workdir,
        description= "",
        haltOnFailure = 1, #haltOnFailure,
        ))
    self.add_refresh()

  def get_hot(self):
    if self.user=='builder': return PhenixBuilder.get_hot(self)
    return [] # don't have any HOT downloads and the difference between
              # anonymous and cciuser is making a mess

  def get_libtbx_configure(self): # modified in derived class PhenixBuilder
    return self.LIBTBX + self.LIBTBX_EXTRA + self.EXTERNAL_CODEBASES

  def get_codebases(self):
    if self.isPlatformWindows(): assert 0, 'not supported'
    if self.user=='builder':
      rc = PhenixBuilder.get_codebases(self)
    else:
      rc = self.EXTERNAL_CODEBASES #+ ['cctbx_project']
    return rc

  def add_tests(self):
    self.add_test_command('qr.test',
                          haltOnFailure=False,
                          )

  def add_dispatchers(self):
    pass

  def rebuild_docs(self):
    pass

def run(root=None):
  usage = """Usage: %prog [options] [actions]

  You may specify one or more actions:
    hot - Update static sources (boost, scons, etc.)
    update - Update source repositories (cctbx, cbflib, etc.)
    base - Build base dependencies (python, hdf5, wxWidgets, etc.)
    build - Build
    tests - Run tests
    doc - Build documentation

  The default action is to run: hot, update, base, build

  You can specify which package will be downloaded, configured,
  and built with "--builder". Current builders:
    cctbx, phenix, xfel, dials, labelit

  You can provide your SourceForge username with "--sfuser", and
  your CCI SVN username with "--cciuser". These will checkout
  and update repositories with your credentials. Some builders,
  like phenix, require this argument for access to certain
  repositories.

  You can run the compilation step in parallel by providing a
  the number of processes using "--nproc".
  Complete build output is shown with "-v" or "--verbose".

  Finally, you may specify a specific Python interpreter
  using "--with-python".

  Example:

    python bootstrap.py --builder=cctbx --sfuser=metalheadd hot update build tests

  """
  parser = optparse.OptionParser(usage=usage)
  # parser.add_option("--root", help="Root directory; this will contain base, modules, build, etc.")
  parser.add_option(
    "--builder",
    help="Builder: cctbx, phenix, xfel, dials, labelit, molprobity",
    default="cctbx")
  parser.add_option("--cciuser", help="CCI SVN username.")
  parser.add_option("--sfuser", help="SourceForge SVN username.")
  parser.add_option("--revert", help="SVN string to revert all SVN trees")
  parser.add_option("--sfmethod",
                    help="SourceForge SVN checkout method.",
                    default="svn+ssh")
  parser.add_option(
    "--git-ssh",
    dest="git_ssh",
    action="store_true",
    help="Use ssh connections for git. This allows you to commit changes without changing remotes and use reference repositories.",
    default=False)
  parser.add_option(
    "--git-reference",
    dest="git_reference",
    help="Path to a directory containing reference copies of repositories for faster checkouts.")
  parser.add_option("--with-python",
                    dest="with_python",
                    help="Use specified Python interpreter")
  parser.add_option("--nproc",
                    help="number of parallel processes in compile step.")
  parser.add_option("--download-only",
                    dest="download_only",
                    action="store_true",
                    help="Do not build, only download prerequisites",
                    default=False)
  parser.add_option("-v",
                    "--verbose",
                    dest="verbose",
                    action="store_true",
                    help="Verbose output",
                    default=False)
  parser.add_option("--skip-base-packages",
                    dest="skip_base",
                    action="store",
                    default="")
  parser.add_option("--force-base-build",
                    dest="force_base_build",
                    action="store_true",
                    default=False)
  parser.add_option("--enable-shared",
                    dest="enable_shared",
                    action="store_true",
                    default=False)
  options, args = parser.parse_args()
  # process external
  options.specific_external_builder=None
  if options.builder.lower() in ["afitt",
                                 "amber",
                                 "rosetta",
                                 ]:
    options.specific_external_builder=options.builder.lower()
    options.builder="external"

  # Root dir
  # options.root = options.root or root

  # Check actions
  allowedargs = ['cleanup', 'hot', 'update', 'base', 'build', 'tests', 'doc']
  args = args or ['hot', 'update', 'base', 'build']
  actions = []
  for arg in args:
    if arg not in allowedargs:
      raise ValueError("Unknown action: %s"%arg)
  for arg in allowedargs:
    if arg in args:
      actions.append(arg)
  print "Performing actions:", " ".join(actions)

  # Check builder
  builders = {
    'cctbx': CCTBXBuilder,
    'phenix': PhenixBuilder,
    'xfel': XFELBuilder,
    'labelit': LABELITBuilder,
    'dials': DIALSBuilder,
    'external': PhenixExternalRegression,
    'molprobity':MOLPROBITYBuilder,
    'qrefine': QRBuilder,
  }
  if options.builder not in builders:
    raise ValueError("Unknown builder: %s"%options.builder)

  auth = { 'git_ssh': options.git_ssh }
  if options.cciuser:
    auth['cciuser'] = options.cciuser
  if options.sfuser:
    auth['sfuser'] = options.sfuser
  if options.sfmethod:
    auth['sfmethod'] = options.sfmethod

  # Build
  builder = builders[options.builder]
  builder(
    category=options.builder,
    subcategory=options.specific_external_builder,
    platform='dev',
    with_python=options.with_python,
    auth=auth,
    hot=('hot' in actions),
    update=('update' in actions),
    revert=options.revert,
    base=('base' in actions),
    build=('build' in actions),
    tests=('tests' in actions),
    doc=('doc' in actions),
    cleanup=("cleanup" in actions),
    nproc=options.nproc,
    verbose=options.verbose,
    download_only=options.download_only,
    skip_base=options.skip_base,
    force_base_build=options.force_base_build,
    enable_shared=options.enable_shared,
  ).run()
  print "\nBootstrap success: %s" % ", ".join(actions)

if __name__ == "__main__":
  run()
