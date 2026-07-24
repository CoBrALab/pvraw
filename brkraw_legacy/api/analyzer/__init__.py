"""Analyzer module initialization.

This module imports and exposes the analyzer classes that turn a
reconstruction's parameters into the values brkraw-legacy derives itself:
scan information and the affine.

Exposed Classes:
    BaseAnalyzer: Provides common features and utilities shared among all analyzers.
    ScanInfoAnalyzer: Specializes in parsing and analyzing scan information from raw datasets.
    AffineAnalyzer: Handles the computation and analysis of affine matrices from dataset parameters.
"""

from .base import BaseAnalyzer
from .scaninfo import ScanInfoAnalyzer
from .affine import AffineAnalyzer

__all__ = ['BaseAnalyzer', 'ScanInfoAnalyzer', 'AffineAnalyzer']
