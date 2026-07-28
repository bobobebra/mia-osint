class MIAError(Exception):
    """Base exception for expected MIA failures."""


class ConfigurationError(MIAError):
    """Raised when configuration cannot be loaded or validated."""


class PluginError(MIAError):
    """Raised for plugin registration or execution errors."""


class TargetError(MIAError):
    """Raised when a target is invalid or cannot be classified."""


class ScanNotFoundError(MIAError):
    """Raised when a scan ID cannot be found in history."""
