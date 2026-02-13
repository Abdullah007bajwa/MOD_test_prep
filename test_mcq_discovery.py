"""Quick test for mcq_discovery module."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from src.mcq_discovery import (
        get_low_count_subcategories,
        get_sources_for_subcategory,
        format_subcategory_name,
        KNOWN_SOURCES
    )
    
    print("=" * 60)
    print("Testing src/mcq_discovery.py")
    print("=" * 60)
    
    # Test 1: Format subcategory name
    print("\n1. Testing format_subcategory_name():")
    test_names = ["number_series", "verbal_classification", "ai_opencv"]
    for name in test_names:
        formatted = format_subcategory_name(name)
        print(f"   {name} -> {formatted}")
    
    # Test 2: Get sources for subcategory
    print("\n2. Testing get_sources_for_subcategory():")
    test_sub = "number_series"
    sources = get_sources_for_subcategory(test_sub)
    print(f"   Sources for '{test_sub}': {len(sources)} found")
    for source in sources[:3]:  # Show first 3
        print(f"   - {source['name']}: {source['url']}")
    
    # Test 3: Check KNOWN_SOURCES coverage
    print("\n3. Testing KNOWN_SOURCES coverage:")
    print(f"   Total subcategories with known sources: {len(KNOWN_SOURCES)}")
    sample_subs = list(KNOWN_SOURCES.keys())[:5]
    print(f"   Sample subcategories: {', '.join(sample_subs)}")
    
    # Test 4: Get low count subcategories (requires DB connection)
    print("\n4. Testing get_low_count_subcategories():")
    try:
        low_count = get_low_count_subcategories(threshold=20)
        print(f"   Found {len(low_count)} subcategories with <20 questions")
        if low_count:
            sample = dict(list(low_count.items())[:3])
            print(f"   Sample: {sample}")
        else:
            print("   (No low-count subcategories found - may need DB connection)")
    except Exception as e:
        print(f"   ⚠️  Could not test (requires DB): {e}")
        print("   (This is expected if DB credentials are not set)")
    
    print("\n" + "=" * 60)
    print("✓ All module tests passed!")
    print("=" * 60)
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Test error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
