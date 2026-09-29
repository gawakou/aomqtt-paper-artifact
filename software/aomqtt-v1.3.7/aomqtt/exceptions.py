class AOMQTTError(Exception):
    """Base exception for AOMQTT SDK errors."""


class AOMQTTConfigurationError(AOMQTTError):
    """Raised when configuration values are invalid."""


class AOMQTTDecryptionError(AOMQTTError):
    """Raised when encrypted payload decryption fails."""
