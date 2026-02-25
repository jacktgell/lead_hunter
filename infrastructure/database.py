import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict

from sqlmodel import Field, Session, SQLModel, create_engine, select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.logger import get_logger
from core.interfaces import ILeadRepository
from infrastructure.migrations import SQLiteAutoMigrator

logger = get_logger(__name__)


class DatabaseOperationError(Exception):
    """Raised when a general database operation fails."""
    pass


class LeadNotFoundError(Exception):
    """Raised when attempting to update a lead that does not exist."""
    pass


class VisitedUrlORM(SQLModel, table=True):
    """Data model representing a previously crawled URL to prevent infinite loops."""
    __tablename__ = "visited_urls"  # type: ignore

    url_hash: str = Field(primary_key=True, description="SHA-256 hash of the URL for O(1) lookups")
    url: str = Field(unique=True, index=True, description="The full visited URL")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SecuredLeadORM(SQLModel, table=True):
    """Data model representing a qualified lead persisted for outreach."""
    __tablename__ = "secured_leads"  # type: ignore

    email: str = Field(primary_key=True, description="The secured contact email")
    company_name: str = Field(description="The name of the secured company")
    founder_name: str = Field(default="Founder", description="The name of the contact")
    reason: str = Field(default="No reason provided.", description="LLM justification for conversion")
    contacted: bool = Field(default=False, index=True, description="Has this lead been emailed?")
    delivery_failed: bool = Field(default=False, description="True if SMTP delivery permanently failed")
    date_found: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LeadDatabase(ILeadRepository):
    """
    Concrete SQLite implementation of the ILeadRepository interface.
    Handles data persistence, deduplication, and basic queue management.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        sqlite_url = f"sqlite:///{self.db_path}"

        # check_same_thread=False is strictly required for multi-threaded queue workers
        self.engine = create_engine(
            sqlite_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
        self._init_db()

    def _init_db(self) -> None:
        """Bootstraps the database schema and triggers dynamic migrations."""
        try:
            SQLModel.metadata.create_all(self.engine)
            SQLiteAutoMigrator.sync_schema(self.engine, SQLModel.metadata)
            logger.info(f"Database schema verified at {self.db_path}")
        except Exception as e:
            logger.critical(f"Failed to initialize database schema: {str(e)}", exc_info=True)
            raise DatabaseOperationError(f"Database initialization failed: {str(e)}")

    def _hash_url(self, url: str) -> str:
        """Generates a deterministic SHA-256 hash for fast primary key lookups."""
        return hashlib.sha256(url.encode('utf-8')).hexdigest()

    def is_url_visited(self, url: str) -> bool:
        url_hash = self._hash_url(url)
        with Session(self.engine) as session:
            statement = select(VisitedUrlORM).where(VisitedUrlORM.url_hash == url_hash)
            return session.exec(statement).first() is not None

    def mark_url_visited(self, url: str) -> None:
        url_hash = self._hash_url(url)
        with Session(self.engine) as session:
            try:
                session.add(VisitedUrlORM(url_hash=url_hash, url=url))
                session.commit()
            except IntegrityError:
                session.rollback()
                # Concurrent crawlers might hit the same URL simultaneously
                logger.debug(f"URL already marked as visited (Integrity collision avoided): {url}")

    def is_email_contacted(self, email: str) -> bool:
        with Session(self.engine) as session:
            statement = select(SecuredLeadORM).where(SecuredLeadORM.email == email)
            return session.exec(statement).first() is not None

    def save_lead(self, email: str, company: str, founder: str, reason: str) -> None:
        with Session(self.engine) as session:
            try:
                lead = SecuredLeadORM(
                    email=email,
                    company_name=company,
                    founder_name=founder,
                    reason=reason
                )
                session.add(lead)
                session.commit()
            except IntegrityError:
                session.rollback()
                logger.warning(f"Attempted to save duplicate lead email. Bypassing: {email}")

    def get_uncontacted_lead(self) -> Optional[SecuredLeadORM]:
        """Fetches the oldest uncontacted lead from the persistent queue."""
        with Session(self.engine) as session:
            statement = select(SecuredLeadORM).where(
                SecuredLeadORM.contacted == False
            ).order_by(SecuredLeadORM.date_found).limit(1)
            return session.exec(statement).first()

    def get_random_uncontacted_lead(self) -> Optional[SecuredLeadORM]:
        """
        Fetches a random uncontacted lead. 
        Note: O(N) complexity due to SQLite RANDOM(). Acceptable for small/medium datasets.
        """
        with Session(self.engine) as session:
            statement = select(SecuredLeadORM).where(
                SecuredLeadORM.contacted == False
            ).order_by(func.random()).limit(1)
            return session.exec(statement).first()

    def mark_contacted(self, email: str) -> None:
        """Flags a lead as successfully processed by the outreach service."""
        with Session(self.engine) as session:
            lead = session.get(SecuredLeadORM, email)
            if not lead:
                logger.error(f"Cannot mark contacted. Lead not found: {email}")
                raise LeadNotFoundError(f"Lead {email} does not exist.")

            lead.contacted = True
            session.add(lead)
            session.commit()
            logger.info(f"Database state updated: {email} marked as contacted.")

    def mark_failed(self, email: str) -> None:
        """Permanently quarantines a lead due to delivery failure."""
        with Session(self.engine) as session:
            lead = session.get(SecuredLeadORM, email)
            if not lead:
                logger.error(f"Cannot mark failed. Lead not found: {email}")
                raise LeadNotFoundError(f"Lead {email} does not exist.")

            lead.contacted = True  # Pull from the active queue
            lead.delivery_failed = True  # Flag as a dead lead
            session.add(lead)
            session.commit()
            logger.info(f"Database state updated: {email} quarantined (delivery failed).")

    def get_stats(self) -> Dict[str, int]:
        """Aggregates system metrics. Wraps potential engine failures."""
        try:
            with Session(self.engine) as session:
                total_leads = session.exec(select(func.count(SecuredLeadORM.email))).one()
                uncontacted = session.exec(
                    select(func.count(SecuredLeadORM.email))
                    .where(SecuredLeadORM.contacted == False)
                ).one()
                visited_urls = session.exec(select(func.count(VisitedUrlORM.url_hash))).one()

                return {
                    "total_leads": total_leads,
                    "uncontacted_leads": uncontacted,
                    "visited_urls": visited_urls
                }
        except SQLAlchemyError as e:
            logger.error(f"Failed to compile database statistics: {str(e)}", exc_info=True)
            raise DatabaseOperationError("Stats aggregation failed.")