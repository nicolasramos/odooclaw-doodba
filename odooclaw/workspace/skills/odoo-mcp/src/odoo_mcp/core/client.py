import json
import logging
from typing import Any, Dict, List, Optional
import requests
from .session import OdooSession
from .exceptions import OdooRPCError

_logger = logging.getLogger(__name__)


class OdooClient:
    """Core client to execute Odoo RPC methods."""

    def __init__(self, session: OdooSession):
        self.odoo_session = session

    def _ensure_authenticated(self) -> None:
        if not self.odoo_session.is_authenticated():
            self.odoo_session.authenticate()

    def call_kw(
        self,
        model: str,
        method: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        sender_id: Optional[int] = None,
    ) -> Any:
        """
        Executes a method on an Odoo model.
        If sender_id is provided, it attempts to route through the secure endpoint /odooclaw/call_kw_as_user
        to enforce Odoo's native Record Rules and Access Rights using the delegation mechanism.
        """
        self._ensure_authenticated()
        args = args or []
        kwargs = kwargs or {}

        # If we have a specific user (sender_id) in the context, we must impersonate to respect security.
        if sender_id:
            return self._call_kw_as_user(sender_id, model, method, args, kwargs)

        # Otherwise, standard call_kw (executed as the admin/bot user itself)
        # Note: In a fully strict mode, you might force sender_id on all MCP endpoints.
        endpoint = f"{self.odoo_session.url}/web/dataset/call_kw/{model}/{method}"

        # Merge session context into kwargs (thread-safe read)
        if "context" not in kwargs:
            kwargs["context"] = self.odoo_session.get_context()

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                "args": args,
                "kwargs": kwargs,
            },
        }

        return self._do_post(endpoint, payload)

    def _call_kw_as_user(
        self,
        user_id: int,
        model: str,
        method: str,
        args: List[Any],
        kwargs: Dict[str, Any],
    ) -> Any:
        """Delegated execution leveraging Odoo's native security via mail_bot_odooclaw endpoint."""
        endpoint = f"{self.odoo_session.url}/odooclaw/call_kw_as_user"

        # Merge session context into kwargs (thread-safe read)
        context = kwargs.pop("context", {})
        merged_context = self.odoo_session.get_context()
        merged_context.update(context)

        payload = {
            "user_id": user_id,
            "model": model,
            "method": method,
            "args": args,
            "kwargs": kwargs,
            "context": merged_context,
        }

        _logger.debug(
            f"Calling endpoint {endpoint} impersonating User {user_id} on {model}.{method}"
        )
        return self._do_post(endpoint, payload)

    def _do_post(self, endpoint: str, payload: dict) -> Any:
        response = self._post_once(endpoint, payload)

        # A reset replaces the database wholesale, which invalidates every
        # session id. The cached session then looks authenticated locally but
        # Odoo no longer knows it, and every call fails until the process is
        # restarted - which is why the bot answered "internal server error"
        # after a reset. Re-authenticate once and retry, so a reset costs one
        # extra round-trip instead of breaking the demo until the next deploy.
        if self._looks_like_stale_session(response):
            _logger.warning(
                "Odoo session rejected (likely invalidated by a database reset); "
                "re-authenticating and retrying once"
            )
            self.odoo_session.authenticate()
            response = self._post_once(endpoint, payload)

        return self._parse(response)

    @staticmethod
    def _looks_like_stale_session(response: requests.Response) -> bool:
        """True only when the response proves the *session* is gone.

        This must be narrow. Retrying a request that failed for a real reason
        would run it twice, and for a write that means duplicating the change.
        So the retry is limited to the two unambiguous "log in again" signals:

          * 401 with the controller's own wording, or
          * a body that explicitly says the session is missing or expired.

        A plain 500 is NOT included on purpose: Odoo answers 500 both when a
        session died and when an ordinary ORM error occurred, and the two are
        indistinguishable from here. The demo's own search_read 500 was an ORM
        permissions error, not a dead session - retrying it would have been
        wrong.
        """
        if response.status_code == 401:
            return True
        try:
            body = response.json()
        except ValueError:
            return False
        text = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
        return ("must be logged in" in text) or ("session" in text and "expired" in text)

    def _post_once(self, endpoint: str, payload: dict) -> requests.Response:
        try:
            return self.odoo_session.session.post(endpoint, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise OdooRPCError(f"RPC transport error: {exc}") from exc

    def _parse(self, response: requests.Response) -> Any:
        response.raise_for_status()
        result = response.json()

        # Check for generic server errors (e.g. from call_kw_as_user controller)
        if result.get("status") == "error":
            raise OdooRPCError(f"Delegated RPC Error: {result.get('reason')}")

        # Check for JSON-RPC specific errors
        if "error" in result:
            err_data = result["error"].get("data", {})
            err_msg = err_data.get("message", "Unknown error")
            err_debug = err_data.get("debug", "")
            raise OdooRPCError(f"RPC Error: {err_msg}\n{err_debug}")

        if "result" in result:
            # call_kw_as_user wraps result in {"status": "ok", "result": ...}
            if (
                isinstance(result["result"], dict)
                and result["result"].get("status") == "ok"
            ):
                return result["result"].get("result")
            return result["result"]

        return True

    def try_call_kw(
        self,
        model: str,
        method: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        sender_id: Optional[int] = None,
        default: Any = None,
    ) -> Any:
        try:
            return self.call_kw(
                model, method, args=args, kwargs=kwargs, sender_id=sender_id
            )
        except OdooRPCError:
            return default

    def get_model_fields(
        self, model: str, sender_id: Optional[int] = None
    ) -> Dict[str, Any]:
        return self.call_kw(model, "fields_get", sender_id=sender_id)

    def try_get_model_fields(
        self, model: str, sender_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        return self.try_call_kw(model, "fields_get", sender_id=sender_id, default=None)

    def model_exists(self, model: str, sender_id: Optional[int] = None) -> bool:
        return self.try_get_model_fields(model, sender_id=sender_id) is not None

    def field_exists(
        self, model: str, field_name: str, sender_id: Optional[int] = None
    ) -> bool:
        fields = self.try_get_model_fields(model, sender_id=sender_id)
        return bool(fields and field_name in fields)
