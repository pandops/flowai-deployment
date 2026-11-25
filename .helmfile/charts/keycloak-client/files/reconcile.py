"""Reconcile the Gateway client's two origin fields through the verified TLS edge."""

import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlencode, urlsplit
from uuid import UUID


class IngressConnection(http.client.HTTPSConnection):
    def __init__(self, origin):
        super().__init__(
            origin.hostname, origin.port, timeout=10,
            context=ssl.create_default_context(cafile="/trust/ca.pem"),
        )

    def connect(self):
        # Keep the public host as the certificate identity. Dial the stable
        # in-namespace Service so no host relay is needed during Helmfile.
        with socket.create_connection(("ingress", 8443), self.timeout) as transport:
            self.sock = self._context.wrap_socket(transport, server_hostname=self.host)


def request(origin, method, path, status, *, body=None, headers=None):
    connection = IngressConnection(origin)
    try:
        connection.request(method, "/idp" + path, body=body, headers=headers or {})
        response = connection.getresponse()
        if response.status != status:
            raise ValueError("unexpected Keycloak status")
        if status != 204:
            return json.load(response)
    finally:
        connection.close()


def reconcile(origin):
    realm = "flowai-e2e"
    client_id = "flowai-api-gateway-e2e"
    discovery = request(
        origin, "GET", f"/realms/{realm}/.well-known/openid-configuration", 200,
    )
    if discovery["issuer"] != f"{origin.geturl()}/idp/realms/{realm}":
        raise ValueError("unexpected issuer")
    admin = Path("/admin")
    token = request(
        origin, "POST", "/realms/master/protocol/openid-connect/token", 200,
        body=urlencode({
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": (admin / "username").read_text(),
            "password": (admin / "password").read_text(),
        }),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    clients_path = f"/admin/realms/{realm}/clients"
    clients = request(
        origin, "GET", clients_path + "?" + urlencode({"clientId": client_id}),
        200, headers=headers,
    )
    if len(clients) != 1 or clients[0]["clientId"] != client_id:
        raise ValueError("expected a unique Gateway client")

    client_path = f"{clients_path}/{UUID(clients[0]['id'])}"
    current = request(origin, "GET", client_path, 200, headers=headers)
    if current["clientId"] != client_id or current["protocol"] != "openid-connect":
        raise ValueError("unexpected client identity")

    desired = {
        "redirectUris": [f"{origin.geturl()}/*", "http://127.0.0.1:*/*"],
        "webOrigins": [origin.geturl(), "http://127.0.0.1:*"],
    }
    if not fields_match(current, desired):
        # The 26.6.3 Admin API preserves omitted properties and attributes.
        # Include the unchanged client identity and type in the update.
        update = {"clientId": client_id, **desired}
        if current.get("type") is not None:
            update["type"] = current["type"]
        request(origin, "PUT", client_path, 204, body=json.dumps(update), headers=headers)
        current = request(origin, "GET", client_path, 200, headers=headers)
        if current["clientId"] != client_id or not fields_match(current, desired):
            raise ValueError("client origin verification failed")


def fields_match(client, desired):
    return all(set(client.get(key) or []) == set(values) for key, values in desired.items())


if __name__ == "__main__":
    try:
        reconcile(urlsplit(sys.argv[1]))
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError):
        sys.exit("Keycloak client reconciliation failed")
    print("Keycloak Gateway client origin verified.")
