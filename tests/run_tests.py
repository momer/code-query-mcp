#!/usr/bin/env python3
import unittest
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def run_tests():
    """Run all tests and return exit code."""
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(__file__)
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.wasSuccessful():
        print("\n✓ All tests passed!")
    else:
        print("\n✗ Some tests failed.")
    
    print("="*70)
    
    # Return appropriate exit code
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help' or sys.argv[1] == '-h':
            print("Usage: python run_tests.py [test_module]")
            print("\nExamples:")
            print("  python run_tests.py                    # Run all tests")
            print("  python run_tests.py test_worker        # Run worker tests")
            print("  python run_tests.py test_queue_operations.TestQueueOperations.test_add_files")
            sys.exit(0)
        else:
            # Run specific test module/case
            unittest.main(module=None, argv=['run_tests.py'] + sys.argv[1:])
    else:
        # Run all tests
        sys.exit(run_tests())