import os
import sys

# Simulated environment locations
env_locations = {
    os.path.normpath(r"C:\Users\varad\OneDrive\Desktop\aws-infra-setup\.conda"),
    os.path.normpath(r"C:\Users\varad\miniconda3"),
}

# Simulated Python location (from sys.executable when conda is active)
py_location = os.path.normpath(r"C:\Users\varad\OneDrive\Desktop\aws-infra-setup\.conda")
py_executable = os.path.normpath(r"C:\Users\varad\OneDrive\Desktop\aws-infra-setup\.conda\python.EXE")

print("Environment locations:")
for loc in env_locations:
    print(f"  {loc}")

print(f"\nPython location: {py_location}")
print(f"Python executable: {py_executable}")

# Test the filtering logic
is_part_of_env = False
for env_loc in env_locations:
    print(f"\nChecking against: {env_loc}")
    print(f"  py_location == env_loc: {py_location == env_loc}")
    print(f"  py_location.startswith(env_loc + os.sep): {py_location.startswith(env_loc + os.sep)}")
    print(f"  py_executable.startswith(env_loc + os.sep): {py_executable.startswith(env_loc + os.sep)}")
    
    if py_location == env_loc or py_location.startswith(env_loc + os.sep):
        is_part_of_env = True
        print(f"  MATCH on location!")
        break
    if py_executable and (py_executable.startswith(env_loc + os.sep)):
        is_part_of_env = True
        print(f"  MATCH on executable!")
        break

print(f"\nFinal result: is_part_of_env = {is_part_of_env}")
print(f"Should filter out: {is_part_of_env}")
