import os
import sys
from dotenv import load_dotenv

# Add workspace directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager

def test():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    
    print("Testing database initialization...")
    print(f"DATABASE_URL env var: {db_url}")
    
    try:
        # Initialize Database connection
        db = DatabaseManager()
        print("[SUCCESS] DatabaseManager instance created successfully!")
        
        # Test basic connection and schema check by getting total users
        users_count = db.get_total_users()
        print(f"[SUCCESS] Connection successful! Total users in database: {users_count}")
        
        # Test schema check for users table columns
        # Try fetching a user (even if not exists, this checks query correctness)
        db.get_user(1)
        print("[SUCCESS] get_user executed successfully without schema errors!")
        
    except Exception as e:
        print("[ERROR] Database test failed with error:")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test()
