#!/usr/bin/env python

"""
Runs unit and integration tests. For usage information run this with '--help'.
"""

import os
import sys
import time
import getopt
import unittest
import StringIO

import test.output
import test.runner
import test.unit.connection.authentication
import test.unit.connection.protocolinfo
import test.unit.socket.control_line
import test.unit.socket.control_message
import test.unit.util.enum
import test.unit.util.system
import test.unit.version
import test.integ.connection.authentication
import test.integ.connection.connect
import test.integ.connection.protocolinfo
import test.integ.socket.control_message
import test.integ.util.conf
import test.integ.util.system
import test.integ.version

import stem.util.enum
import stem.util.log as log
import stem.util.term as term

OPT = "uic:l:t:h"
OPT_EXPANDED = ["unit", "integ", "config=", "targets=", "log=", "tor=", "no-color", "help"]
DIVIDER = "=" * 70

CONFIG = {
  "test.arg.unit": False,
  "test.arg.integ": False,
  "test.arg.log": None,
  "test.arg.tor": "tor",
  "test.arg.no_color": False,
  "target.config": {},
  "target.description": {},
  "target.prereq": {},
  "target.torrc": {},
}

TARGETS = stem.util.enum.Enum(*[(v, v) for v in (
  "ONLINE",
  "RELATIVE",
  "RUN_NONE",
  "RUN_OPEN",
  "RUN_PASSWORD",
  "RUN_COOKIE",
  "RUN_MULTIPLE",
  "RUN_SOCKET",
  "RUN_SCOOKIE",
  "RUN_PTRACE",
  "RUN_ALL",
)])

DEFAULT_RUN_TARGET = TARGETS.RUN_OPEN

# Tests are ordered by the dependencies so the lowest level tests come first.
# This is because a problem in say, controller message parsing, will cause all
# higher level tests to fail too. Hence we want the test that most narrowly
# exhibits problems to come first.

UNIT_TESTS = (
  test.unit.util.enum.TestEnum,
  test.unit.util.system.TestSystem,
  test.unit.version.TestVersion,
  test.unit.socket.control_message.TestControlMessage,
  test.unit.socket.control_line.TestControlLine,
  test.unit.connection.authentication.TestAuthenticate,
  test.unit.connection.protocolinfo.TestProtocolInfoResponse,
)

INTEG_TESTS = (
  test.integ.util.conf.TestConf,
  test.integ.util.system.TestSystem,
  test.integ.version.TestVersion,
  test.integ.socket.control_message.TestControlMessage,
  test.integ.connection.protocolinfo.TestProtocolInfo,
  test.integ.connection.authentication.TestAuthenticate,
  test.integ.connection.connect.TestConnect,
)

# TODO: move into settings.cfg when we have multi-line options
HELP_MSG = """Usage runTests.py [OPTION]
Runs tests for the stem library.

  -u, --unit            runs unit tests
  -i, --integ           runs integration tests
  -c, --config PATH     path to a custom test configuration
  -t, --target TARGET   comma separated list of extra targets for integ tests
  -l, --log RUNLEVEL    includes logging output with test results, runlevels:
                          TRACE, DEBUG, INFO, NOTICE, WARN, ERROR
      --tor PATH        custom tor binary to run testing against
      --no-color        displays testing output without color
  -h, --help            presents this help

  Integration targets:"""

def load_user_configuration(test_config):
  """
  Parses our commandline arguments, loading our custom test configuration if
  '--config' was provided and then appending arguments to that. This does some
  sanity checking on the input, printing an error and quitting if validation
  fails.
  """
  
  arg_overrides, config_path = {}, None
  
  try:
    opts, args = getopt.getopt(sys.argv[1:], OPT, OPT_EXPANDED)
  except getopt.GetoptError, exc:
    print "%s (for usage provide --help)" % exc
    sys.exit(1)
  
  for opt, arg in opts:
    if opt in ("-u", "--unit"):
      arg_overrides["test.arg.unit"] = "true"
    elif opt in ("-i", "--integ"):
      arg_overrides["test.arg.integ"] = "true"
    elif opt in ("-c", "--config"):
      config_path = os.path.abspath(arg)
    elif opt in ("-t", "--targets"):
      integ_targets = arg.split(",")
      
      # validates the targets
      if not integ_targets:
        print "No targets provided"
        sys.exit(1)
      
      for target in integ_targets:
        if not target in TARGETS:
          print "Invalid integration target: %s" % target
          sys.exit(1)
        else:
          target_config = test_config.get("target.config", {}).get(target)
          if target_config: arg_overrides[target_config] = "true"
    elif opt in ("-l", "--log"):
      arg_overrides["test.arg.log"] = arg.upper()
    elif opt in ("--tor"):
      arg_overrides["test.arg.tor"] = arg
    elif opt in ("-h", "--help"):
      # Prints usage information and quits. This includes a listing of the
      # valid integration targets.
      
      print HELP_MSG
      
      # gets the longest target length so we can show the entries in columns
      target_name_length = max(map(len, TARGETS))
      description_format = "    %%-%is - %%s" % target_name_length
      
      for target in TARGETS:
        print description_format % (target, CONFIG["target.description"].get(target, ""))
      
      print
      
      sys.exit()
  
  # load a testrc if '--config' was given, then apply arguments
  
  if config_path:
    try:
      test_config.load(config_path)
    except IOError, exc:
      print "Unable to load testing configuration at '%s': %s" % (config_path, exc)
      sys.exit(1)
  
  for key, value in arg_overrides.items():
    test_config.set(key, value)
  
  # basic validation on user input
  
  log_config = CONFIG["test.arg.log"]
  if log_config and not log_config in log.LOG_VALUES:
    print "'%s' isn't a logging runlevel, use one of the following instead:" % log_config
    print "  TRACE, DEBUG, INFO, NOTICE, WARN, ERROR"
    sys.exit(1)
  
  tor_config = CONFIG["test.arg.tor"]
  if not os.path.exists(tor_config) and not stem.util.system.is_available(tor_config):
    print "Unable to start tor, '%s' does not exists." % tor_config
    sys.exit(1)

if __name__ == '__main__':
  start_time = time.time()
  
  # loads and validates our various configurations
  test_config = stem.util.conf.get_config("test")
  test_config.sync(CONFIG)
  
  settings_path = os.path.join(test.runner.STEM_BASE, "test", "settings.cfg")
  test_config.load(settings_path)
  
  load_user_configuration(test_config)
  
  if not CONFIG["test.arg.unit"] and not CONFIG["test.arg.integ"]:
    print "Nothing to run (for usage provide --help)\n"
    sys.exit()
  
  # if we have verbose logging then provide the testing config
  our_level = stem.util.log.logging_level(CONFIG["test.arg.log"])
  info_level = stem.util.log.logging_level(stem.util.log.INFO)
  
  if our_level <= info_level: test.output.print_config(test_config)
  
  error_tracker = test.output.ErrorTracker()
  output_filters = (
    error_tracker.get_filter(),
    test.output.strip_module,
    test.output.align_results,
    test.output.colorize,
  )
  
  stem_logger = log.get_logger()
  logging_buffer = log.LogBuffer(CONFIG["test.arg.log"])
  stem_logger.addHandler(logging_buffer)
  
  if CONFIG["test.arg.unit"]:
    test.output.print_divider("UNIT TESTS", True)
    
    for test_class in UNIT_TESTS:
      test.output.print_divider(test_class.__module__)
      suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
      test_results = StringIO.StringIO()
      unittest.TextTestRunner(test_results, verbosity=2).run(suite)
      
      sys.stdout.write(test.output.apply_filters(test_results.getvalue(), *output_filters))
      print
      
      test.output.print_logging(logging_buffer)
    
    print
  
  if CONFIG["test.arg.integ"]:
    test.output.print_divider("INTEGRATION TESTS", True)
    integ_runner = test.runner.get_runner()
    
    # Queue up all the targets with torrc options we want to run against.
    
    integ_run_targets = []
    all_run_targets = [t for t in TARGETS if CONFIG["target.torrc"].get(t)]
    
    if test_config.get("test.target.run.all", False):
      # test against everything with torrc options
      integ_run_targets = all_run_targets
    else:
      for target in all_run_targets:
        target_config = CONFIG["target.config"].get(target)
        
        if target_config and test_config.get(target_config, False):
          integ_run_targets.append(target)
    
    # if we didn't specify any targets then use the default
    if not integ_run_targets:
      integ_run_targets.append(DEFAULT_RUN_TARGET)
    
    # Determine targets we don't meet the prereqs for. Warnings are given about
    # these at the end of the test run so they're more noticeable.
    
    our_version, skip_targets = None, []
    
    for target in integ_run_targets:
      target_prereq = CONFIG["target.prereq"].get(target)
      
      if target_prereq:
        # lazy loaded to skip system call if we don't have any prereqs
        if not our_version:
          our_version = stem.version.get_system_tor_version(CONFIG["test.arg.tor"])
        
        if our_version < stem.version.Requirement[target_prereq]:
          skip_targets.append(target)
    
    for target in integ_run_targets:
      if target in skip_targets: continue
      
      try:
        # converts the 'target.torrc' csv into a list of test.runner.Torrc enums
        torrc_opts = []
        
        for opt in test_config.get_str_csv("target.torrc", [], sub_key = target):
          if opt in test.runner.Torrc.keys():
            torrc_opts.append(test.runner.Torrc[opt])
          else:
            print "'%s' isn't a test.runner.Torrc enumeration" % opt
            sys.exit(1)
        
        integ_runner.start(CONFIG["test.arg.tor"], extra_torrc_opts = torrc_opts)
        
        print term.format("Running tests...", term.Color.BLUE, term.Attr.BOLD)
        print
        
        for test_class in INTEG_TESTS:
          test.output.print_divider(test_class.__module__)
          suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
          test_results = StringIO.StringIO()
          unittest.TextTestRunner(test_results, verbosity=2).run(suite)
          
          sys.stdout.write(test.output.apply_filters(test_results.getvalue(), *output_filters))
          print
          
          test.output.print_logging(logging_buffer)
      except OSError:
        pass
      finally:
        integ_runner.stop()
    
    if skip_targets:
      print
      
      for target in skip_targets:
        req_version = stem.version.Requirement[CONFIG["target.prereq"][target]]
        print term.format("Unable to run target %s, this requires tor version %s" % (target, req_version), term.Color.RED, term.Attr.BOLD)
      
      print
    
    # TODO: note unused config options afterward?
  
  runtime_label = "(%i seconds)" % (time.time() - start_time)
  
  if error_tracker.has_error_occured():
    print term.format("TESTING FAILED %s" % runtime_label, term.Color.RED, term.Attr.BOLD)
    
    for line in error_tracker:
      print term.format("  %s" % line, term.Color.RED, term.Attr.BOLD)
  else:
    print term.format("TESTING PASSED %s" % runtime_label, term.Color.GREEN, term.Attr.BOLD)
    print

