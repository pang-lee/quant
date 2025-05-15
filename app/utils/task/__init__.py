# utils/task/__init__.py
import glob, os, importlib

current_dir = os.path.dirname(__file__)
for filepath in glob.glob(os.path.join(current_dir, '*.py')):
    if os.path.basename(filepath) != '__init__.py':
        module_name = os.path.basename(filepath)[:-3]
        module = importlib.import_module(f'.{module_name}', __name__)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not attr_name.startswith('_'):
                globals()[attr_name] = attr