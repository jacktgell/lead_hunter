import unittest
import os
import uuid
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel
from infrastructure.database import LeadDatabase
from infrastructure.migrations import SQLiteAutoMigrator


class TestDatabaseInfrastructure(unittest.TestCase):
    def setUp(self):

        self.db_name = f"test_{uuid.uuid4().hex}.db"
        self.db_path = self.db_name
        self.engine = create_engine(f"sqlite:///{self.db_path}")

    def tearDown(self):
        # Fix: Aggressive cleanup
        self.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                print(f"Warning: Could not delete {self.db_path} due to file lock.")

    def test_auto_migration_appends_columns(self):
        """Verifies that missing columns are added to an existing table."""
        # 1. Create a "Legacy" table manually
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE secured_leads (email VARCHAR PRIMARY KEY, company_name VARCHAR)"))

        # 2. Run the Migrator
        SQLiteAutoMigrator.sync_schema(self.engine, SQLModel.metadata)

        # 3. Verify column existence
        inspector = inspect(self.engine)
        columns = [col['name'] for col in inspector.get_columns("secured_leads")]
        self.assertIn("delivery_failed", columns)
        self.assertIn("founder_name", columns)

    def test_lead_deduplication(self):
        """Ensures the repository pattern prevents duplicate leads via IntegrityErrors."""
        db = LeadDatabase(self.db_path)
        db.save_lead("test@corp.com", "Corp", "CEO", "Reason")
        # Attempt duplicate save
        db.save_lead("test@corp.com", "Corp", "CEO", "Reason")

        stats = db.get_stats()
        self.assertEqual(stats["total_leads"], 1)

        # Important: Close connection so file can be deleted
        db.engine.dispose()