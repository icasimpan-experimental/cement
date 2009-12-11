"""Cement methods to setup the framework for applications using it."""
import os
from pkg_resources import get_distribution

from cement import plugins as cement_plugins
from cement import config, hooks, commands
from cement.core.log import setup_logging, get_logger
from cement.core.options import init_parser, parse_options
from cement.core.options import set_config_opts_per_cli_opts
from cement.core.exc import CementConfigError, CementRuntimeError
from cement.core.configuration import set_config_opts_per_file, \
                                      validate_config

CEMENT_ABI = "20091207"



class CementCommand(object):
    def __init__(self, cli_opts=None, cli_args=None, handlers=None):
        self.hidden = False # whether to display in command list
        self.cli_opts = cli_opts
        self.cli_args = cli_args
        self.handlers = handlers
    
    def help(self):
        """Display command help information."""
        print "No help information available."
    
    def run(self):
        """Run the command actions."""
        print "No actions have been defined for this command."
        

class CementPlugin(object):
    def __init__(self):
        self.version = None
        self.description = ""
        self.commands = {}
        self.handlers = {}
        self.config = {'config_source': ['defaults']}
        self.options = init_parser(config)
        

def get_abi_version():
    return CEMENT_ABI
    
def ensure_abi_compat(module_name, required_abi):
    if int(required_abi) == int(CEMENT_ABI):
        pass
    else:
        raise CementRuntimeError, \
            "%s requires abi version %s which differs from cement(abi) %s." % \
                (module_name, required_abi, CEMENT_ABI)
    
    
def define_hook_namespace(namespace):
    """
    Define a hook namespace that plugins can register hooks in.
    """
    if hooks.has_key(namespace):
        raise CementRuntimeError, "Hook name '%s' already defined!" % namespace
    hooks[namespace] = []
    
def register_hook(**kwargs):
    """
    Decorator function for plugins to register hooks.  Used as:
    
    @register_hook()
    def my_hook():
        ...
    """
    def decorate(func):
        if not hooks.has_key(func.__name__):
            raise CementRuntimeError, "Hook name '%s' is not define!" % func.__name__
        hooks[func.__name__].append(
            (int(kwargs.get('weight', 0)), func.__name__, func)
        )
        return func
    return decorate

def run_hooks(namespace, *args, **kwargs):
    """
    Run all defined hooks in the namespace.  Returns a list of return data.
    """
    if not hooks.has_key(namespace):
        CementRuntimeError, "Hook name '%s' is not defined!" % namespace
    hooks[namespace].sort() # will order based on weight
    for hook in hooks[namespace]:
        res = hook[2](*args, **kwargs)
        yield res

def register_command(**kwargs):
    """
    Decorator function for plugins to register commands.  Used as:
    
    @register_command()
    class MyCommand(CementCommand):
        ...
    """
    def decorate(func):
        setattr(func, 'hidden', kwargs.get('hidden', False))
        commands[kwargs['name']] = func
        return func
    return decorate

def run_command(command_name, cli_args, cli_opts, handlers):
    """
    Run all defined hooks in the namespace.  Returns a list of return data.
    """
    if not commands.has_key(command_name):
        CementArgumentError, "Unknown command.  See --help?" % command_name
    commands[command_name](cli_args, cli_opts, handlers)
    
def lay_cement(default_app_config=None, version_banner=None):
    """
    Primary method to setup an application for Cement.  
    
    Arguments:
    
    config => dict containing application config.
    version_banner => Option txt displayed for --version
    """
    

    #dcf.update(config) # override the actual defaults
    #config = dcf # take the new config with changes
    global config
    config.update(default_app_config)
    validate_config(config)
    
    # define default hooks
    define_hook_namespace('global_option_hook')
    
    if not version_banner:
        version_banner = get_distribution(config['app_egg_name']).version
        
    for cf in config['config_files']:
        set_config_opts_per_file(config, config['app_module'], cf)
        
    options = init_parser(version_banner)
    (commands, handlers, options) = load_all_plugins(options)
    (cli_opts, cli_args) = parse_options(options)
    config = set_config_opts_per_cli_opts(config, cli_opts)
    setup_logging()
    
    return (cli_opts, cli_args, commands, handlers)

def load_plugin(plugin):
    """
    Load a cement type plugin.  
    
    Arguments:
    
    config  => The existing config dict.
    plugin  => Name of the plugin to load.
    """
    if config.has_key('show_plugin_load') and config['show_plugin_load']:
        print 'loading %s plugin' % plugin
    
    try: 
        app_module = __import__(config['app_module'])
    except ImportError, e:
        raise CementConfigError, e
            
    # try from 'app_module' first, then cement name space    
    try:
        plugins_module = __import__('%s.plugins' % config['app_module'],
                                    globals(), locals(),
                                    [plugin], 0)
        pluginobj = getattr(plugins_module, plugin)
    except AttributeError, e:
        # we allow all apps to use cement plugins like their own.        
        try:
            plugins_module = __import__('cement.plugins', globals(), locals(),
                                        [plugin], 0)
            pluginobj = getattr(plugins_module, plugin)
        except AttributeError, e:
            raise CementConfigError, \
                'failed to load %s plugin: %s' % (plugin, e)    
    
    plugin_cls = pluginobj.register_plugin()
    
    ensure_abi_compat(plugin_cls.__module__, plugin_cls.required_abi)

    plugin_config_file = os.path.join(
        config['plugin_config_dir'], '%s.plugin' % plugin
        )
    plugin_cls.config = set_config_opts_per_file(plugin_cls.config, plugin, 
                                                 plugin_config_file)
    return plugin_cls
        
        
def load_all_plugins(options):
    """
    Attempt to load all enabled plugins.  Passes the existing config and 
    options object to each plugin and allows them to add/update each.
    """
    plugin_commands = {}
    plugin_handlers = {}
    for plugin in config['enabled_plugins']:
        plugin_cls = load_plugin(plugin)

        # add the plugin commands
        for key in plugin_cls.commands:
            if plugin_commands.has_key(key):
                raise CementRuntimeError, \
                    'Command conflict, %s command already exists!' % key
            plugin_commands[key] = plugin_cls.commands[key]

        # add the plugin handlers
        for key in plugin_cls.handlers:
            if plugin_handlers.has_key(key):
                raise CementRuntimeError, \
                    'Handler conflict, %s handler already exists!' % key
            plugin_handlers[key] = plugin_cls.handlers[key]

        # add the plugin 
        config['plugins'][plugin] = plugin_cls
        
        # add the plugin options
        for opt_obj in run_hooks('global_option_hook'):
            for opt in opt_obj.parser._get_all_options(): 
                if opt.get_opt_string() == '--help':
                    pass
                elif opt.get_opt_string() == '--version': 
                    pass
                else:
                    options.parser.add_option(opt)
        
    return (plugin_commands, plugin_handlers, options)

