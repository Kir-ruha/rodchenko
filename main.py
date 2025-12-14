import asyncio
import uuid
from typing import Annotated, Optional, List

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from .db import (
    authenticate_user,
    create_user,
    get_db,
    get_user,
    init_db,
    create_seeker_request,
    get_seeker_request_by_uuid,
    fulfill_seeker_request,
    create_ghostlink_insight,
    get_ghostlink_insights,
    get_random_ghostlink_insight,
    create_finder_insight_request,
    get_finder_insight_request,
    get_all_ghostlink_requests,
    accept_finder_insight_request,
    reject_finder_insight_request,
    SeekerRequestOrm,
    GhostlinkInsightOrm,
    FinderInsightRequestOrm,
    get_all_fulfilled_seeker_requests
)
from fastapi.staticfiles import StaticFiles
from .models import User, UserCreate, SeekerRequestBase, GhostlinkInsightBase, FinderItemBase
import os


templates = Jinja2Templates(directory="src/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan, title="DarkBazaar")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET_KEY"))
app.mount("/static", StaticFiles(directory="src/static"), name="static")


async def get_current_user(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    username = request.session.get('username')
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_orm = await get_user(db, username)
    if not user_orm:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return User.model_validate(user_orm)


def render_profile_template(
        request: Request,
        user: User,
        found_item: Optional[FinderItemBase] = None,
        error: Optional[str] = None,
        success_message: Optional[str] = None
    ) -> HTMLResponse:
        context = {
            "request": request,
            "role": user.role,
            "username": user.username,
            "seeker_requests": [SeekerRequestBase.model_validate(req) for req in user.seeker_requests],
            "ghostlink_insights": [GhostlinkInsightBase.model_validate(ins) for ins in user.ghostlink_insights],
            "finder_insight_request_as_finder": user.finder_insight_request_as_finder,
            "found_item": found_item,
            "error": error,
            "success_message": success_message,
        }
        return templates.TemplateResponse("profile.html", context)


def render_relationships_template(
        request: Request,
        user: User,
        ghostlink_requests: Optional[List[FinderInsightRequestOrm]] = None,
        error: Optional[str] = None
    ) -> HTMLResponse:
        context = {
            "request": request,
            "user": user,
            "ghostlink_requests": ghostlink_requests,
            "error": error,
        }
        return templates.TemplateResponse("relationships.html", context)


@app.post("/users/register")
async def register_new_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("seeker"),
    db: AsyncSession = Depends(get_db)
):
    user_create = UserCreate(username=username, password=password, role=role)
    new_user = await create_user(db, user_create)
    if not new_user:
        return templates.TemplateResponse("register.html", {"request": request, "error": "User with this name already exists"})
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.post("/users/login")
async def login_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    user = await authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "User with this credentials doesn't exist"})
    request.session["username"] = user.username
    return RedirectResponse(url="/profile", status_code=status.HTTP_302_FOUND)


@app.post('/logout')
async def logout(request: Request, current_user: Annotated[User, Depends(get_current_user)]):
    request.session.pop("username", None)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@app.get('/', response_class=HTMLResponse)
async def get_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get('/register', response_class=HTMLResponse)
async def get_register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get('/login', response_class=HTMLResponse)
async def get_login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get('/profile', response_class=HTMLResponse)
async def get_profile_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    user_orm_refreshed = await get_user(db, current_user.username)
    if not user_orm_refreshed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found after refresh")

    updated_user = User.model_validate(user_orm_refreshed)

    return render_profile_template(
        request=request,
        user=updated_user,
    )



@app.post('/seeker/create_request')
async def create_new_seeker_request(
    request: Request,
    item_uuid: uuid.UUID = Form(...),
    description: str = Form(...),
    contact_info: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != 'seeker':
        return render_profile_template(request=request, user=current_user, error="Access denied: only 'seeker' role can create requests.")
    
    seeker_request_base = SeekerRequestBase(uuid=item_uuid, description=description, contact_info=contact_info)
    error = await create_seeker_request(db, current_user, seeker_request_base)
    if error:
        return render_profile_template(request=request, user=current_user, error=error)
    
    return RedirectResponse(url="/profile", status_code=status.HTTP_302_FOUND)


@app.post('/finder/find_item')
async def find_item(
    request: Request,
    item_uuid: uuid.UUID = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != 'finder':
        return render_profile_template(request=request, user=current_user, error="Access denied: only 'finder' role can find items.")
    
    seeker_request = await get_seeker_request_by_uuid(db, item_uuid)
    if not seeker_request:
        return render_profile_template(request=request, user=current_user, error="Item with this UUID is not currently being sought.")
    
    await fulfill_seeker_request(db, item_uuid, current_user.username)

    found_item_data = FinderItemBase(
        uuid=seeker_request.uuid,
        description=seeker_request.description,
        contact_info=seeker_request.contact_info
    )
    
    return render_profile_template(request=request, user=current_user, found_item=found_item_data, success_message="You successfully found an item!")


@app.post('/ghostlink/create_insight')
async def create_new_ghostlink_insight(
    request: Request,
    insight_uuid: uuid.UUID = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != 'ghostlink':
        return render_profile_template(request=request, user=current_user, error="Access denied: only 'ghostlink' role can create insights.")
    
    error = await create_ghostlink_insight(db, current_user, insight_uuid)
    if error:
        return render_profile_template(request=request, user=current_user, error=error) # Изменено
    
    return RedirectResponse(url="/profile", status_code=status.HTTP_302_FOUND)


@app.get('/ghostlink/requests', response_class=HTMLResponse)
async def get_ghostlink_requests_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    if current_user.role != 'ghostlink':
        return render_profile_template(request=request, user=current_user, error="Access denied: only 'ghostlink' role can view requests.")

    ghostlink_requests = await get_all_ghostlink_requests(db, current_user.username)
    
    return render_relationships_template(
        request=request,
        user=current_user,
        ghostlink_requests=ghostlink_requests
    )


@app.post('/ghostlink/accept_request')
async def accept_ghostlink_request_endpoint(
    request: Request,
    finder_username: str = Form(...),
    username: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not current_user.finder_insight_requests_as_ghostlink:
        return render_profile_template(request=request, user=current_user, error="Access denied: only \'ghostlink\' role can accept request.")
    
    result = await accept_finder_insight_request(db, current_user, finder_username, username)
    if isinstance(result, str):
        ghostlink_requests = await get_all_ghostlink_requests(db, current_user.username)
        return render_relationships_template(request=request, user=current_user, ghostlink_requests=ghostlink_requests, error=result)
    
    return RedirectResponse(url="/ghostlink/accept/successful", status_code=status.HTTP_302_FOUND)


@app.get('/ghostlink/accept/successful', response_class=HTMLResponse)
async def get_ghostlink_accept_successful_page(request: Request):
    return templates.TemplateResponse("successful_accept.html", {"request": request})


@app.post('/ghostlink/reject_request')
async def reject_ghostlink_request_endpoint(
    request: Request,
    finder_username: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != 'ghostlink':
        return render_profile_template(request=request, user=current_user, error="Access denied: only 'ghostlink' role can reject requests.")
    
    error = await reject_finder_insight_request(db, current_user, finder_username)
    if error:
        ghostlink_requests = await get_all_ghostlink_requests(db, current_user.username)
        return render_relationships_template(request=request, user=current_user, ghostlink_requests=ghostlink_requests, error=error)
    
    return RedirectResponse(url="/ghostlink/reject/successful", status_code=status.HTTP_302_FOUND)


@app.get('/ghostlink/reject/successful', response_class=HTMLResponse)
async def get_ghostlink_reject_successful_page(request: Request):
    return templates.TemplateResponse("succesful_reject.html", {"request": request})


@app.get('/finder/get_fulfilled_descriptions')
async def get_fulfilled_descriptions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    username: str = "anonymous"
) -> List[FinderItemBase]:
    if current_user.role != 'finder':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: only 'finder' role can view fulfilled descriptions.")

    fulfilled_requests_orm = await get_all_fulfilled_seeker_requests(db, username)
    return [FinderItemBase.model_validate(req) for req in fulfilled_requests_orm]


@app.post('/finder/request_insight')
async def request_insight_from_ghostlink(
    request: Request,
    ghostlink_username: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != 'finder':
        return render_profile_template(request=request, user=current_user, error="Access denied: only 'finder' role can request insights.")
    
    error = await create_finder_insight_request(db, current_user, ghostlink_username)
    if error:
        return render_profile_template(request=request, user=current_user, error=error)
    
    return RedirectResponse(url="/finder/request_insight/successful", status_code=status.HTTP_302_FOUND)


@app.get('/finder/request_insight/successful', response_class=HTMLResponse)
async def get_finder_insight_request_as_finder_insight_successful_page(request: Request):
    return templates.TemplateResponse("successful_request.html", {"request": request})

