import os


def print_internal_error(io_handler=None):
    import sys
    import traceback
    if io_handler is None:
        io_handler = sys.stderr
    traceback.print_exception(*sys.exc_info(),
                              file=io_handler)


class Error(Exception):
    """ Base class for other custom exceptions """
    message = None


class FileNotValidError(Error):
    """ Raised when the file is not valid format """

    def __init__(self, file_name=None, data_type=None):
        self.file_name = None
        self.data_type = None

        if file_name is not None:
            self.file_name = os.path.basename(file_name)
            if os.path.isdir(file_name):
                object_type = 'directory'
            else:
                object_type = 'file'
            if data_type is not None:
                self.data_type = data_type
                self.message = f"The {object_type} '{self.file_name}' is not valid {self.data_type}"
            else:
                self.message = f"The {object_type} '{self.file_name}' is not valid"
        else:
            self.message = "The file is not valid"


class ArchiveFailedError(Error):
    """ Raised when the archive process is failed [designed for pvraw module] """
    file_name = None

    def __init__(self, file_name=None):
        if file_name is not None:
            self.file_name = os.path.basename(file_name)
            self.message = f"The data '{self.file_name}' is not archived"
        else:
            self.message = "Archive failed to execute"


class RemoveFailedError(Error):
    """ Raise when the os.remove process is failed """
    file_name = None

    def __init__(self, file_name=None):
        if file_name is not None:
            self.file_name = os.path.basename(file_name)
            self.message = f"The file '{self.file_name}' is not removed"
        else:
            self.message = "Remove failed to execute"


class RenameFailedError(Error):
    """ Raised when the os.rename process is failed (OSError)"""
    file1_name = None
    file2_name = None

    def __init__(self, file1_name=None, file2_name=None):
        if file1_name is not None:
            self.file1_name = os.path.basename(file1_name)
        if file2_name is not None:
            self.file2_name = os.path.basename(file2_name)
        if (self.file1_name is not None) and (self.file2_name is not None):
            self.message = f"Rename failed to execute from:'{self.file1_name}' to:'{self.file2_name}'"
        else:
            self.message = "Rename failed to execute"


class UnexpectedError(Error):
    """ Raised when unexpected error occurred """

    def __init__(self, message=None):
        print_internal_error()
        if message is None:
            self.message = "Unexpected error"
        else:
            self.message = message


class ValueConflictInField(Error):
    """ Raised when input value was conflicted with other """

    def __init__(self, message=None):
        if message is None:
            self.message = "The value is conflicted"
        else:
            self.message = message


class InvalidValueInField(Error):
    """ Raise when the invalid value is detected in field """

    def __init__(self, message=None):
        if message is None:
            self.message = "Invalid value is detected"
        else:
            self.message = message


class InvalidApproach(Error):
    """ Raise when the user try invalid approach """

    def __init__(self, message=None):
        print_internal_error()
        if message is None:
            self.message = "Invalid approach!"
        else:
            self.message = message
