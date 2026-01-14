# debug/test_pse_v2_migration.py
"""
Test script to verify PSE API v2 migration is working correctly.
Run with: uv run python debug/test_pse_v2_migration.py
"""
import sys
from pathlib import Path

# Add parent directory to path to import api_handlers
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, date
from api_handlers import get_pse_data, PSE_URL
import requests

def test_api_endpoint():
    """Test that the API endpoint is accessible and returns data."""
    print("=" * 60)
    print("Testing PSE API v2 Endpoint")
    print("=" * 60)
    print(f"URL: {PSE_URL}")
    
    # Test with today's date
    test_date = date.today()
    print(f"\nFetching data for: {test_date}")
    
    try:
        response = requests.get(PSE_URL, params={"$filter": f"business_date eq '{test_date}'"})
        print(f"Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ FAILED: API returned status {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return False
        
        data = response.json()
        if "value" not in data:
            print(f"❌ FAILED: Response missing 'value' key")
            print(f"Response keys: {list(data.keys())}")
            return False
        
        records = data.get("value", [])
        print(f"✅ SUCCESS: Retrieved {len(records)} records")
        
        if len(records) == 0:
            print("⚠️  WARNING: No records returned (might be normal if no data for today)")
            return True
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_v2_field_names():
    """Test that the response contains v2 field names (dtime, period, rce_pln)."""
    print("\n" + "=" * 60)
    print("Testing V2 Field Names")
    print("=" * 60)
    
    test_date = date.today()
    
    try:
        data = get_pse_data(test_date)
        
        if data is None:
            print("⚠️  WARNING: No data returned (might be normal)")
            return True
        
        if len(data) == 0:
            print("⚠️  WARNING: Empty data array (might be normal)")
            return True
        
        # Check first record for v2 fields
        first_record = data[0]
        print(f"\nFirst record keys: {list(first_record.keys())}")
        
        required_v2_fields = ["dtime", "period", "rce_pln", "business_date"]
        missing_fields = []
        found_fields = []
        
        for field in required_v2_fields:
            if field in first_record:
                found_fields.append(field)
                print(f"✅ Found v2 field: {field}")
            else:
                missing_fields.append(field)
                print(f"❌ Missing v2 field: {field}")
        
        # Check for old v1 fields (should NOT be present)
        old_v1_fields = ["doba", "udtczas_oreb"]
        found_old_fields = []
        for field in old_v1_fields:
            if field in first_record:
                found_old_fields.append(field)
                print(f"⚠️  WARNING: Found old v1 field: {field} (should not be present)")
        
        if missing_fields:
            print(f"\n❌ FAILED: Missing required v2 fields: {missing_fields}")
            return False
        
        if found_old_fields:
            print(f"\n⚠️  WARNING: Old v1 fields still present: {found_old_fields}")
            print("   (This might be okay if API returns both, but code should use v2 fields)")
        
        print(f"\n✅ SUCCESS: All required v2 fields present")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_parsing_logic():
    """Test that the parsing logic works with v2 field names."""
    print("\n" + "=" * 60)
    print("Testing Parsing Logic")
    print("=" * 60)
    
    test_date = date.today()
    
    try:
        data = get_pse_data(test_date)
        
        if data is None or len(data) == 0:
            print("⚠️  WARNING: No data to test parsing")
            return True
        
        # Simulate the parsing logic from app.py
        def parse_pse_datetime(dtime_str):
            """Parse PSE datetime from v2 API format (dtime is already a full datetime string)."""
            try:
                # v2 API returns dtime as full datetime string: "2026-01-14 00:15:00"
                dt = datetime.strptime(dtime_str, "%Y-%m-%d %H:%M:%S")
                return dt
            except Exception as e:
                raise ValueError(f"Error parsing datetime: {dtime_str} - {e}")
        
        parsed_count = 0
        error_count = 0
        
        for item in data[:5]:  # Test first 5 records
            try:
                if not isinstance(item, dict):
                    continue
                
                # Use v2 field names - dtime is already a full datetime string
                dt = parse_pse_datetime(item["dtime"])
                price = float(item["rce_pln"])
                
                parsed_count += 1
                print(f"✅ Parsed: {dt.isoformat()} - Price: {price} PLN")
                
            except (KeyError, ValueError) as e:
                error_count += 1
                print(f"❌ Parse error: {e}")
                print(f"   Item keys: {list(item.keys())}")
        
        if error_count > 0:
            print(f"\n❌ FAILED: {error_count} parsing errors out of {len(data[:5])} records")
            return False
        
        print(f"\n✅ SUCCESS: Successfully parsed {parsed_count} records")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("PSE API v2 Migration Verification Test")
    print("=" * 60)
    
    results = []
    
    # Test 1: API endpoint accessibility
    results.append(("API Endpoint", test_api_endpoint()))
    
    # Test 2: V2 field names
    results.append(("V2 Field Names", test_v2_field_names()))
    
    # Test 3: Parsing logic
    results.append(("Parsing Logic", test_parsing_logic()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED - Migration appears successful!")
    else:
        print("❌ SOME TESTS FAILED - Please review the errors above")
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

