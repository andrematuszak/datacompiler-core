"""Optional Matecat API integration for human XLIFF review.

Matecat remains an external CAT editor: DataCompiler prepares the XLIFF,
Matecat hosts the human editing session, and DataCompiler imports the reviewed
XLIFF before rebuilding the PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from datacompiler.model.document import Document
from .xliff import TranslationUnit, export_xliff


_MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class MatecatProject:
    """Project details returned by Matecat after XLIFF submission."""

    response: dict
    base_url: str
    uploaded_filename: str | None = None

    @property
    def project_id(self) -> str | None:
        value = _find_value(self.response, {"id_project", "project_id", "projectId"})
        return str(value) if value is not None else None

    @property
    def project_password(self) -> str | None:
        value = _find_value(
            self.response, {"project_password", "projectPassword", "password"},
        )
        return str(value) if value is not None else None

    @property
    def job_id(self) -> str | None:
        jobs = _find_value(self.response, {"jobs", "job_list", "jobList"})
        if isinstance(jobs, list) and jobs:
            value = _find_value(jobs[0], {"id_job", "job_id", "jobId", "id"})
            if value is not None:
                return str(value)
        return _find_value(self.response, {"id_job", "job_id", "jobId"})

    @property
    def job_password(self) -> str | None:
        jobs = _find_value(self.response, {"jobs", "job_list", "jobList"})
        if isinstance(jobs, list) and jobs:
            value = _find_value(jobs[0], {"job_password", "jobPassword", "password"})
            if value is not None:
                return str(value)
        return _find_value(self.response, {"job_password", "jobPassword"})

    @property
    def editor_url(self) -> str | None:
        """Return a URL supplied by Matecat, if its response includes one."""
        return _find_editor_url(self.response)


def _find_value(value, names: set[str]):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names and item is not None:
                return item
        for item in value.values():
            found = _find_value(item, names)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_value(item, names)
            if found is not None:
                return found
    return None


def _find_editor_url(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if (isinstance(item, str) and item.startswith(("http://", "https://"))
                    and ("editor" in key.lower() or "translate" in item.lower())):
                return item
        for item in value.values():
            found = _find_editor_url(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_editor_url(item)
            if found:
                return found
    return None


class MatecatClient:
    """Small standard-library client for Matecat's project and XLIFF APIs.

    The host and API credentials are configurable so the same workflow can use
    Matecat's hosted service now and a self-hosted instance later.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 60,
    ):
        self.api_key = api_key or os.environ.get("MATECAT_API_KEY")
        if not self.api_key:
            raise ValueError("Set MATECAT_API_KEY or pass api_key to MatecatClient.")
        self.base_url = (
            base_url or os.environ.get("MATECAT_BASE_URL") or "https://www.matecat.com"
        ).rstrip("/")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("Matecat base_url must be an absolute HTTP(S) URL.")
        self.timeout = timeout

    def create_project(
        self,
        xliff_path: str | Path,
        *,
        source_language: str,
        target_language: str,
        project_name: str | None = None,
        subject: str = "general",
    ) -> MatecatProject:
        """Upload one XLIFF file and create a Matecat human-review project."""
        path = Path(xliff_path)
        size = path.stat().st_size
        if size > _MAX_UPLOAD_BYTES:
            raise ValueError("Matecat's documented per-file upload limit is 200 MB.")
        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", path.name)
        boundary = "DataCompiler-" + uuid.uuid4().hex
        fields = {
            "project_name": project_name or path.stem,
            "source": source_language,
            "target": target_language,
            "subject": subject,
        }
        body = bytearray()
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii")
            )
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("ascii")
        )
        body.extend(b"Content-Type: application/x-xliff+xml\r\n\r\n")
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
        payload = self._request(
            "/api/v1/new", method="POST", data=bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Matecat returned an unexpected project response.")
        return MatecatProject(payload, self.base_url, filename)

    def get_project(self, project_id: str, project_password: str) -> dict:
        """Fetch project details, including jobs when available."""
        project_id = urllib.parse.quote(str(project_id), safe="")
        project_password = urllib.parse.quote(str(project_password), safe="")
        payload = self._request(f"/api/v2/projects/{project_id}/{project_password}")
        if not isinstance(payload, dict):
            raise RuntimeError("Matecat returned an unexpected project response.")
        return payload

    def get_project_urls(self, project_id: str, project_password: str) -> dict:
        """Fetch Matecat's editor and download URLs for a project."""
        project_id = urllib.parse.quote(str(project_id), safe="")
        project_password = urllib.parse.quote(str(project_password), safe="")
        payload = self._request(
            f"/api/v2/projects/{project_id}/{project_password}/urls",
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Matecat returned unexpected project URLs.")
        return payload

    def download_job_xliff(
        self,
        job_id: str,
        job_password: str,
        destination: str | Path,
        *,
        filename: str | None = None,
    ) -> Path:
        """Download the XLIFF export for a reviewed Matecat job."""
        safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "reviewed.xlf")
        path = "/api/v2/xliff/{}/{}/{}".format(
            urllib.parse.quote(str(job_id), safe=""),
            urllib.parse.quote(str(job_password), safe=""),
            urllib.parse.quote(safe_filename, safe=""),
        )
        content = self._request(path, expect_json=False)
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    def download_reviewed_xliff(
        self,
        project: MatecatProject,
        destination: str | Path,
        *,
        filename: str | None = None,
    ) -> Path:
        """Download the project's first job after human review is complete."""
        project_id = project.job_id
        job_password = project.job_password
        details = project.response
        if not project_id or not job_password:
            project_id_value, project_password = project.project_id, project.project_password
            if project_id_value and project_password:
                details = self.get_project(project_id_value, project_password)
                jobs = _find_value(details, {"jobs", "job_list", "jobList"})
                if isinstance(jobs, list) and jobs:
                    project_id = _find_value(jobs[0], {"id_job", "job_id", "jobId", "id"})
                    job_password = _find_value(
                        jobs[0], {"job_password", "jobPassword", "password"},
                    )
        if not project_id or not job_password:
            raise ValueError(
                "Matecat response did not expose the job credentials needed for XLIFF export. "
                "Inspect project.response and pass job_id/job_password to download_job_xliff."
            )
        return self.download_job_xliff(
            str(project_id), str(job_password), destination,
            filename=filename or project.uploaded_filename or "reviewed.xlf",
        )

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str | None = None,
        expect_json: bool = True,
    ):
        headers = {"x-matecat-key": self.api_key, "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Matecat API returned HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Matecat: {exc.reason}") from exc
        if not expect_json:
            return result
        try:
            return json.loads(result.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Matecat returned a non-JSON API response.") from exc


def import_matecat_xliff(
    client: MatecatClient,
    project: MatecatProject,
    destination: str | Path,
    *,
    expected_units: list[TranslationUnit],
    filename: str | None = None,
):
    """Download and validate Matecat's XLIFF while preserving stable unit IDs."""
    from .xliff import import_xliff

    path = client.download_reviewed_xliff(project, destination, filename=filename)
    translation = import_xliff(path, expected_units=expected_units)
    for unit in translation.units.values():
        if unit.target:
            # A machine-quality score applies to the machine output, not to the
            # post-edited text. Keep the human-reviewed state and avoid showing
            # a stale score in the resulting PDF annotations.
            unit.quality_score = None
            unit.quality_model = None
            unit.review_recommended = False
            unit.provider = "matecat"
            unit.human_reviewed = True
    return translation


def submit_document_to_matecat(
    document: Document,
    client: MatecatClient,
    xliff_path: str | Path,
    *,
    source_language: str,
    target_language: str,
    project_name: str | None = None,
    subject: str = "general",
) -> tuple[MatecatProject, list[TranslationUnit]]:
    """Export DataCompiler segments and submit that XLIFF for human review."""
    units = export_xliff(
        document,
        xliff_path,
        source_language=source_language,
        target_language=target_language,
    )
    project = client.create_project(
        xliff_path,
        source_language=source_language,
        target_language=target_language,
        project_name=project_name,
        subject=subject,
    )
    return project, units

