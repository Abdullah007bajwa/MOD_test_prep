"""
Test Supabase connection and table structure.
Run after executing create_supabase_tables.sql
"""

from db import get_supabase_uncached

def test_connection():
    print("Testing Supabase connection...")
    try:
        client = get_supabase_uncached()
        print("✓ Client created successfully")
        
        # Test questions table
        response = client.table('questions').select('id').limit(1).execute()
        print(f"✓ Questions table exists (rows: {len(response.data)})")
        
        # Test user_stats table
        response = client.table('user_stats').select('id').limit(1).execute()
        print(f"✓ user_stats table exists (rows: {len(response.data)})")
        
        # Test sessions table
        response = client.table('sessions').select('id').limit(1).execute()
        print(f"✓ sessions table exists (rows: {len(response.data)})")
        
        # Test session_answers table
        response = client.table('session_answers').select('id').limit(1).execute()
        print(f"✓ session_answers table exists (rows: {len(response.data)})")
        
        # Count questions by source
        response = client.table('questions').select('source', count='exact').execute()
        print(f"\n✓ Total questions in database: {response.count or 0}")
        
        # Get breakdown by source
        response = client.rpc('exec_sql', {
            'query': 'SELECT source, COUNT(*) as count FROM questions GROUP BY source'
        }).execute()
        
        print("\n=== All tests passed! ===")
        print("\nReady to run:")
        print("  python -m src.indiabix_scraper_v2 --max-topics 19 --max-questions 1000 --backup-json")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nPlease:")
        print("  1. Run create_supabase_tables.sql in Supabase SQL Editor")
        print("  2. Check .env has SUPABASE_URL and SUPABASE_KEY")
        return False
    
    return True

if __name__ == "__main__":
    test_connection()
