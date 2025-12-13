#!/usr/bin/env python3
"""
Timing Utilities for AWS Infrastructure Operations
Created: 2025-07-06 13:14:32 UTC
Author: varadharajaan
"""

import time
import functools
from datetime import datetime
from typing import Dict, Any, Optional
import inspect
from text_symbols import Symbols

class TimingTracker:
    """Class to track timing of operations"""
    
    def __init__(self):
        self.timings = {}
        self.start_times = {}
        self.operation_count = 0
    
    def start_operation(self, operation_name: str):
        """Start tracking time for an operation"""
        self.start_times[operation_name] = time.time()
        self.operation_count += 1
    
    def end_operation(self, operation_name: str) -> float:
        """End tracking time for an operation and return duration"""
        if operation_name not in self.start_times:
            return 0.0
        
        duration = time.time() - self.start_times[operation_name]
        self.timings[operation_name] = duration
        del self.start_times[operation_name]
        return duration
    
    def get_summary(self) -> Dict[str, float]:
        """Get summary of all timings"""
        return self.timings.copy()
    
    def format_duration_bk(self, seconds: float) -> str:
        """Format duration in human readable format"""
        if seconds < 60:
            return f"{seconds:.2f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.2f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.2f}h"

    def format_duration(self, seconds: float) -> str:
        """Format duration in human readable format, e.g., 2 hours 20 minutes 30 seconds"""
        seconds = int(round(seconds))
        if seconds == 0:
            return "0 seconds"
        parts = []
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if secs or not parts:
            parts.append(f"{secs} second{'s' if secs != 1 else ''}")
        return " ".join(parts)
    
    def reset(self):
        """Reset all timings"""
        self.timings.clear()
        self.start_times.clear()
        self.operation_count = 0

def timing_decorator(operation_name: str = None):
    """
    Decorator to time method execution
    Usage: @timing_decorator("Operation Name")
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Use method name if operation_name not provided
            op_name = operation_name or func.__name__.replace('_', ' ').title()
            
            # Initialize timing_tracker if not exists
            if not hasattr(self, 'timing_tracker'):
                self.timing_tracker = TimingTracker()
            
            # Start timing
            self.timing_tracker.start_operation(op_name)
            
            # Log start
            if hasattr(self, 'log_operation'):
                self.log_operation("INFO", f"{Symbols.START} Starting: {op_name}")
            else:
                print(f"{Symbols.START} Starting: {op_name}")
            
            try:
                # Execute the method
                result = func(self, *args, **kwargs)
                
                # End timing and log
                duration = self.timing_tracker.end_operation(op_name)
                formatted_duration = self.timing_tracker.format_duration(duration)
                
                if hasattr(self, 'log_operation'):
                    self.log_operation("INFO", f"{Symbols.OK} Completed: {op_name} in {formatted_duration}")
                else:
                    print(f"{Symbols.OK} Completed: {op_name} in {formatted_duration}")
                
                return result
                
            except Exception as e:
                # End timing even on error
                duration = self.timing_tracker.end_operation(op_name)
                formatted_duration = self.timing_tracker.format_duration(duration)
                
                if hasattr(self, 'log_operation'):
                    self.log_operation("ERROR", f"{Symbols.ERROR} Failed: {op_name} after {formatted_duration} - {str(e)}")
                else:
                    print(f"{Symbols.ERROR} Failed: {op_name} after {formatted_duration} - {str(e)}")
                raise
                
        return wrapper
    return decorator

def add_timing_methods(cls):
    """
    Class decorator to add timing methods to any class
    Usage: @add_timing_methods
    """
    
    def initialize_timing_tracker(self):
        """Initialize timing tracker for the instance"""
        if not hasattr(self, 'timing_tracker'):
            self.timing_tracker = TimingTracker()

    def start_timing(self, operation_name: str = None):
        """Start timing an operation (auto-detect name if not provided)"""
        if operation_name is None:
            # Get the caller function name
            frame = inspect.currentframe()
            caller_frame = frame.f_back
            operation_name = caller_frame.f_code.co_name
        self.initialize_timing_tracker()
        self.timing_tracker.start_operation(operation_name)
        if hasattr(self, 'log_operation'):
            self.log_operation("INFO", f"{Symbols.START} Starting: {operation_name}")
        else:
            print(f"{Symbols.START} Starting: {operation_name}")

    def end_timing(self, operation_name: str = None):
        """End timing an operation and log duration (auto-detect name if not provided)"""
        if operation_name is None:
            frame = inspect.currentframe()
            caller_frame = frame.f_back
            operation_name = caller_frame.f_code.co_name
        if hasattr(self, 'timing_tracker'):
            duration = self.timing_tracker.end_operation(operation_name)
            formatted_duration = self.timing_tracker.format_duration(duration)
            if hasattr(self, 'log_operation'):
                self.log_operation("INFO", f"{Symbols.OK} Completed: {operation_name} in {formatted_duration}")
            else:
                print(f"{Symbols.OK} Completed: {operation_name} in {formatted_duration}")
            return duration
        return 0.0
    
    def get_timing_summary(self) -> Dict[str, float]:
        """Get timing summary for all operations"""
        if hasattr(self, 'timing_tracker'):
            return self.timing_tracker.get_summary()
        return {}
    
    def print_timing_summary(self, title: str = "TIMING SUMMARY"):
        """Print comprehensive timing summary"""
        if not hasattr(self, 'timing_tracker'):
            return
        
        timings = self.timing_tracker.get_summary()
        if not timings:
            return
        
        print(f"\n{Symbols.TIMER}  {title}")
        print("=" * (len(title) + 10))
        
        total_time = sum(timings.values())
        
        # Sort by duration (longest first)
        sorted_timings = sorted(timings.items(), key=lambda x: x[1], reverse=True)
        
        for operation, duration in sorted_timings:
            percentage = (duration / total_time * 100) if total_time > 0 else 0
            formatted_duration = self.timing_tracker.format_duration(duration)
            print(f"  {operation:<35} {formatted_duration:<10} ({percentage:.1f}%)")
        
        print("-" * (len(title) + 10))
        total_formatted = self.timing_tracker.format_duration(total_time)
        print(f"  {'TOTAL TIME':<35} {total_formatted:<10} (100.0%)")
        print("=" * (len(title) + 10))
    
    def reset_timing(self):
        """Reset all timing data"""
        if hasattr(self, 'timing_tracker'):
            self.timing_tracker.reset()
    
    # Add methods to the class
    cls.initialize_timing_tracker = initialize_timing_tracker
    cls.start_timing = start_timing
    cls.end_timing = end_timing
    cls.get_timing_summary = get_timing_summary
    cls.print_timing_summary = print_timing_summary
    cls.reset_timing = reset_timing
    
    return cls