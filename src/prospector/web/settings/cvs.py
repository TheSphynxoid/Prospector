"""Profile CVs: upload, download, mark as main, replace, delete. Each action returns the CV list fragment."""
import json

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from prospector.context import AppContext
from prospector.store.cvs import MAX_CV_BYTES
from prospector.web.dashboard import templates


def make_cv_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/settings/profile/cvs")

    def fragment(request: Request, status: int = 200, error: str = "", toast: str = ""):
        headers = {"HX-Trigger": json.dumps({"toast": {"msg": toast}})} if toast else None
        return templates.TemplateResponse(request, "settings/_cvs.html", {"cvs": ctx.cvs.list(), "cv_error": error},
                                          status_code=status, headers=headers)

    async def read(file: UploadFile | None) -> bytes:
        if file is None:
            raise ValueError("Pick a file to upload.")
        data = await file.read(MAX_CV_BYTES + 1)  # one byte over is enough to know it's too big
        return data

    def cv_or_404(cv_id: int):
        cv = ctx.cvs.get(cv_id)
        if cv is None:
            raise HTTPException(404)
        return cv

    @router.post("")
    async def upload(request: Request):
        form = await request.form()
        try:
            data = await read(form.get("file") if hasattr(form.get("file"), "read") else None)
            ctx.cvs.add(form.get("label", ""), form.get("language", ""), form["file"].filename or "cv", data)
        except ValueError as e:
            return fragment(request, 400, str(e))
        return fragment(request, toast="CV added")

    @router.get("/{cv_id}/download")
    def download(cv_id: int):
        cv = cv_or_404(cv_id)
        path = ctx.cvs.path(cv)
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type=cv.content_type, filename=cv.filename,
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                                     "Content-Disposition": f'attachment; filename="{cv.filename}"'})

    @router.post("/{cv_id}/main")
    def main(request: Request, cv_id: int):
        cv_or_404(cv_id)
        ctx.cvs.set_main(cv_id)
        return fragment(request, toast="Main CV set")

    @router.post("/{cv_id}/replace")
    async def replace(request: Request, cv_id: int):
        cv_or_404(cv_id)
        form = await request.form()
        try:
            data = await read(form.get("file") if hasattr(form.get("file"), "read") else None)
            ctx.cvs.replace(cv_id, form["file"].filename or "cv", data)
        except ValueError as e:
            return fragment(request, 400, str(e))
        return fragment(request, toast="CV replaced")

    @router.post("/{cv_id}/delete")
    def delete(request: Request, cv_id: int):
        cv_or_404(cv_id)
        ctx.cvs.delete(cv_id)
        return fragment(request, toast="CV removed")

    return router
