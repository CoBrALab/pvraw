from xnippet import XnippetManager, setup_logging

from .lib import BrukerLoader

__version__ = '0.5.0'
config = XnippetManager(package_name=__package__, 
                        package_version=__version__,
                        package__file__=__file__,
                        config_filename='config.yaml')

__all__ = ['BrukerLoader', '__version__', 'config', 'setup_logging']

def load(path):
    return BrukerLoader(path)
