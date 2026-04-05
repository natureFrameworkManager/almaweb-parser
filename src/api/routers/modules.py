from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from database.database import SessionDep
from database.model import Module

router = APIRouter(prefix="/modules", tags=["Modules"])


@router.get("", summary="List all modules")
def get_modules(
    session: SessionDep
):
    """
    Retrieve a list of all modules
    """
    # Base query: select only Module rows
    query = select(Module)

    # Fetch distinct modules (join filters can produce duplicates)
    modules = session.exec(query.distinct()).all()

    return modules


@router.get("/{module_id}", summary="Get a module by ID")
def get_module(module_id: int, session: SessionDep):
    """
    Retrieve a single module by its ID.

    Returns **404** if the module does not exist.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")

    return module
