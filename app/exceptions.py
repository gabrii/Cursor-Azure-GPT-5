"""Exceptions for the application."""


class ConfigurationError(ValueError):
    """Exception raised for configuration errors."""

    preamble = None

    def get_response_content(self):
        """Returns a formated error message inclduing the preamble and the message."""
        message = self.args[0].replace("\n", "\n\t")

        return f"{self.preamble}\n\n\t{message}"


class ServiceConfigurationError(ConfigurationError):
    """Exception raised for configuration errors in the service configuration."""

    preamble = "Service configuration error, check your .env file."


class CursorConfigurationError(ConfigurationError):
    """Exception raised for configuration errors in Cursor configuration."""

    preamble = "Cursor configuration error, check your Cursor settings."
