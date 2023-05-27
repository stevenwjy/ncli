
"""
The `utils` module contains a collection of utility functions that can be used across projects.
"""

from datetime import datetime, timedelta

from click import echo
import toml


def format_duration(duration: float) -> str:
    """
    Formats a duration into a time string in the format of 'HH:MM:SS' or 'MM:SS'.

    This function accepts a duration in seconds and converts it into a formatted string. If the duration
    is more than an hour, it formats the string in the 'HH:MM:SS' format. Otherwise, it formats the string
    in the 'MM:SS' format.

    Parameters:
    duration (float): The duration in seconds.

    Returns:
    str: The duration formatted as a string in 'HH:MM:SS' or 'MM:SS' format.

    Examples:
    >>> format_duration(3661)
    '1:01:01'

    >>> format_duration(61)
    '1:01'
    """
    time_delta = timedelta(seconds=duration)
    hours, remainder = divmod(time_delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_duration_from_ms(value: int) -> str:
    """
    Converts a duration in milliseconds to a formatted time string.

    The resulting time string is formatted as 'H:MM:SS', where H is hours, MM is minutes
    (with leading zero, if required), and SS is seconds (with leading zero, if required).

    Args:
        value (int): The duration in milliseconds.

    Returns:
        str: The formatted time string.
    """
    sec = value // 1000  # round down to second

    val_sec = sec % 60
    val_min = (sec % (60 * 60)) // 60
    val_hour = sec // (60 * 60)

    return f'{val_hour}:{val_min:02d}:{val_sec:02d}'


def extract_date(date_string):
    """
    Extracts the date component from a date string in ISO format.

    Args:
        date_string (str): A date string in the format YYYY-MM-DDTHH:MM:SS.SSSZ.

    Returns:
        str: The date component of the input string in YYYY-MM-DD format.

    """
    # Convert the string to a datetime object
    date_object = datetime.fromisoformat(date_string.replace('Z', '+00:00'))

    # Extract the date component from the datetime object
    date_only = date_object.date()

    # Return the date component as a string in YYYY-MM-DD format
    return str(date_only)


def format_date(date_string):
    """
    Converts a date string in the format 'YYYY-MM-DD HH:MM:SS.sss' to the format '%a, %d %b %Y %H:%M:%S %z'.

    Args:
        date_string (str): A date string in the format 'YYYY-MM-DD HH:MM:SS.sss'.

    Returns:
        str: A string in the format '%a, %d %b %Y %H:%M:%S %z'.

    """
    # Parse the date string into a datetime object
    date_object = datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S.%f")

    # Format the datetime object into the desired string format
    formatted_date = date_object.astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

    # Return the formatted date string
    return formatted_date


def prompt_user(question: str) -> bool:
    """
    Prompts the user to provide input in the form of a yes or no answer and returns the input as a boolean.

    Args:
        question (str): The question to display to the user when prompting for input.

    Returns:
        bool: True if the user answers 'y' or 'Y', False if the user answers 'n' or 'N'.
    """
    while True:
        input_str = input(f"{question} (y/n): ").strip().lower()
        if input_str == "y":
            return True
        if input_str == "n":
            return False
        echo("Unable to parse input. Please respond using the provided options (case-insensitive).")


def toml_dumps_with_newline(data):
    toml_str = toml.dumps(data)
    lines = toml_str.splitlines()
    formatted_lines = []

    for line in lines:
        if len(formatted_lines) > 0 and line.startswith("[["):
            formatted_lines.append("")
        formatted_lines.append(line)

    formatted_lines.append("")  # newline at the end

    return "\n".join(formatted_lines)
