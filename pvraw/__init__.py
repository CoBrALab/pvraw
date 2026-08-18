from .lib import BrukerLoader

__version__ = '0.6.0'

__all__ = ['BrukerLoader', '__version__']

def load(path):
    return BrukerLoader(path)
