import logging.config

from meet_recorder import consolecolor as ccolor


fmt = '[%(levelname)s] %(name)s: %(message)s'


class CustomFormatter(logging.Formatter):
    """Logging colored formatter, adapted from https://stackoverflow.com/a/56944256/3638629"""

    colorfy_attr = '%(levelname)s'

    def __init__(self, fmt):
        super().__init__()

        self.fmt = fmt

        self.FORMATS = {
            logging.DEBUG: self.fmt,
            logging.INFO: self.fmt.replace(self.colorfy_attr, ccolor.blue(self.colorfy_attr)),
            logging.WARNING: self.fmt.replace(self.colorfy_attr, ccolor.yellow(self.colorfy_attr)),
            logging.ERROR: self.fmt.replace(self.colorfy_attr, ccolor.red(self.colorfy_attr)),
            logging.CRITICAL: ccolor.bold_red(self.fmt),
        }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def color_formatter(fmt):
    def _factory():
        return CustomFormatter(fmt)

    return _factory


def setup(colors, verbose):
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': fmt
            },
            'default_color': {
                '()': color_formatter(fmt),
            },
        },
        'handlers': {
            'stdout': {
                'class': 'logging.StreamHandler',
                'formatter': 'default_color' if colors else 'default',
                'stream': 'ext://sys.stdout'
            }
        },
        'loggers': {
            '': {
                'handlers': ['stdout'],
                'level': 'DEBUG' if verbose else 'INFO',
                'propagate': True
            }
        }
    }

    logging.config.dictConfig(logging_config)
