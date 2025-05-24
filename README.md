# BMS Controller Optimization

This directory contains scripts for communicating with a Battery Management System (BMS) via a serial connection.

## Files

- `bms.py` - Original BMS communication script
- `bms_optimized.py` - Optimized version of the BMS script
- `constants.py` - Constants used by both scripts
- `test_bms_optimized.py` - Test script for the optimized version

## Optimizations

The following optimizations were made to the original script:

1. **Object-Oriented Structure**
   - Converted the procedural code to a class-based structure
   - Encapsulated related functionality within methods
   - Improved code organization and maintainability

2. **Error Handling**
   - More consistent exception handling
   - Better error messages with f-strings
   - Proper resource cleanup in case of errors

3. **Code Documentation**
   - Added docstrings to all methods
   - Improved comments for complex operations
   - Better variable naming for readability

4. **Performance Improvements**
   - Optimized string operations using f-strings
   - Used list comprehensions for bit manipulations
   - Reduced redundant operations

5. **Resource Management**
   - Added proper connection closing
   - Better handling of serial port resources
   - Improved state management

6. **Code Structure**
   - Added a main() function for better script organization
   - Separated concerns into distinct methods
   - Made the code more modular and maintainable

## Usage

### Original Script

```bash
python bms.py /dev/ttyUSB0
```

### Optimized Script

```bash
python bms_optimized.py /dev/ttyUSB0
```

Or directly:

```bash
./bms_optimized.py /dev/ttyUSB0
```

### Testing

To test the optimized script without actual hardware:

```bash
./test_bms_optimized.py
```

## API Usage

The optimized script can also be imported and used as a module:

```python
from bms_optimized import BmsController

# Create a BMS controller
bms = BmsController('/dev/ttyUSB0')

# Connect to the BMS
if bms.connect():
    # Get all data
    bms.get_all_data()
    
    # Access the data
    print(bms.output)
    
    # Close the connection
    bms.close()
```

## Output Format

Both scripts produce the same JSON output format, containing:

- BMS version information
- Serial numbers
- Pack information (voltage, current, capacity, etc.)
- Cell information
- Temperature readings
- Warning and error states
