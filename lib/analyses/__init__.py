"""Analysis plugins package — import all modules to trigger registration."""
from lib.analyses import time_domain  # noqa: F401
from lib.analyses import fft_analysis  # noqa: F401
from lib.analyses import psd_analysis  # noqa: F401
from lib.analyses import srs_analysis  # noqa: F401
from lib.analyses import spectrogram_analysis  # noqa: F401
from lib.analyses import velocity_analysis  # noqa: F401
from lib.analyses import cepstrum_analysis  # noqa: F401
from lib.analyses import orbit_analysis  # noqa: F401
