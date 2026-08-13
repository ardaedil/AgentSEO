from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


class SandboxError(RuntimeError):
    def __init__(self, message: str, code: str = "INVALID_REQUEST") -> None:
        super().__init__(message)
        self.code = code


INITIAL_STATES: dict[str, dict[str, Any]] = {
    "billing": {
        "customers": {
            "cus_john": {
                "id": "cus_john",
                "name": "John Rivera",
                "email": "john@example.com",
                "status": "active",
            },
            "cus_alice": {
                "id": "cus_alice",
                "name": "Alice Chen",
                "email": "alice@example.com",
                "status": "active",
            },
        },
        "subscriptions": {
            "sub_john": {
                "id": "sub_john",
                "customer_id": "cus_john",
                "status": "active",
                "cancel_at_period_end": False,
            },
            "sub_alice": {
                "id": "sub_alice",
                "customer_id": "cus_alice",
                "status": "active",
                "cancel_at_period_end": False,
            },
        },
        "invoices": {
            "inv_john": {
                "id": "inv_john",
                "customer_id": "cus_john",
                "status": "open",
                "amount": 7900,
            },
            "inv_alice": {
                "id": "inv_alice",
                "customer_id": "cus_alice",
                "status": "paid",
                "amount": 4900,
            },
        },
        "payment_methods": {
            "pm_john": {"id": "pm_john", "customer_id": "cus_john", "valid": True, "last4": "4242"},
        },
        "refunds": {},
    },
    "ecommerce": {
        "customers": {
            "cus_jane": {
                "id": "cus_jane",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "status": "active",
            }
        },
        "orders": {
            "ord_1": {"id": "ord_1", "customer_id": "cus_jane", "total": 8500, "refunded": False},
            "ord_2": {"id": "ord_2", "customer_id": "cus_jane", "total": 4300, "refunded": False},
        },
        "shipments": {
            "ship_1": {"id": "ship_1", "order_id": "ord_1", "status": "failed"},
            "ship_2": {"id": "ship_2", "order_id": "ord_2", "status": "delivered"},
        },
        "refunds": {},
    },
    "crm": {
        "contacts": {"con_sarah": {"id": "con_sarah", "name": "Sarah", "company_id": "co_acme"}},
        "companies": {"co_acme": {"id": "co_acme", "name": "Acme Inc."}},
        "owners": {"own_sarah": {"id": "own_sarah", "name": "Sarah"}},
        "opportunities": {
            "opp_1": {
                "id": "opp_1",
                "company_id": "co_acme",
                "status": "open",
                "value": 25000,
                "owner_id": None,
            },
            "opp_2": {
                "id": "opp_2",
                "company_id": "co_acme",
                "status": "open",
                "value": 18000,
                "owner_id": None,
            },
            "opp_3": {
                "id": "opp_3",
                "company_id": "co_acme",
                "status": "won",
                "value": 64000,
                "owner_id": None,
            },
        },
    },
    "generic": {},
}


@dataclass
class StatefulSandbox:
    domain: str

    def __post_init__(self) -> None:
        self.reset()

    def reset(self, initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
        self.state = deepcopy(initial_state or INITIAL_STATES.get(self.domain, {}))
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.state)

    def execute(self, tool: str, arguments: dict[str, Any]) -> Any:
        self._inject_fault(tool, arguments)
        if tool.startswith("experiment_read_context_"):
            return {
                "operation": tool,
                "read_only": True,
                "experimental_distractor": True,
                "state_collections": sorted(self.state),
            }
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return self._generic(tool, arguments)
        return handler(arguments)

    def _inject_fault(self, tool: str, arguments: dict[str, Any]) -> None:
        """Apply task-scoped deterministic faults without changing canonical tool behavior."""

        faults = self.state.get("_faults", [])
        if not isinstance(faults, list):
            return
        for fault in faults:
            if not isinstance(fault, dict) or fault.get("tool") != tool:
                continue
            expected = fault.get("arguments", {})
            if any(arguments.get(key) != value for key, value in expected.items()):
                continue
            remaining = int(fault.get("remaining", 1))
            if remaining <= 0:
                continue
            fault["remaining"] = remaining - 1
            replacement = fault.get("replacement_id")
            message = str(fault.get("message", "Injected task fault"))
            if replacement:
                message = f"{message} Suggested replacement identifier: {replacement}."
            raise SandboxError(message, str(fault.get("code", "TEMPORARY_UNAVAILABLE")))

    def _collection(self, name: str) -> dict[str, Any]:
        collection = self.state.get(name)
        if not isinstance(collection, dict):
            raise SandboxError(f"Unknown collection: {name}", "NOT_FOUND")
        return collection

    def _generic(self, tool: str, args: dict[str, Any]) -> Any:
        lowered = tool.lower()
        aliases = {
            "companies": "companies",
            "company": "companies",
            "opportunit": "opportunities",
            "customer": "customers",
            "subscription": "subscriptions",
            "invoice": "invoices",
            "order": "orders",
            "shipment": "shipments",
            "owner": "owners",
            "contact": "contacts",
        }
        entity = next((plural for singular, plural in aliases.items() if singular in lowered), None)
        if not entity:
            raise SandboxError(f"Unsupported sandbox tool: {tool}", "NOT_IMPLEMENTED")
        data = self._collection(entity)
        if lowered.startswith(("search", "find", "list", "lookup")):
            query = str(args.get("query") or args.get("email") or args.get("name") or "").lower()
            results = list(data.values())
            if query:
                results = [item for item in results if query in str(item).lower()]
            for key in ("status", "company_id", "customer_id", "order_id"):
                if key in args:
                    results = [item for item in results if item.get(key) == args[key]]
            if "min_value" in args:
                results = [item for item in results if item.get("value", 0) > args["min_value"]]
            return results
        if lowered.startswith("get"):
            object_id = args.get("id") or args.get(f"{entity[:-1]}_id")
            if object_id not in data:
                raise SandboxError(f"{entity[:-1].title()} not found", "NOT_FOUND")
            return deepcopy(data[object_id])
        if lowered.startswith(("delete", "terminate")):
            object_id = args.get("id") or args.get(f"{entity[:-1]}_id")
            if object_id not in data:
                raise SandboxError("Object not found", "NOT_FOUND")
            data[object_id]["status"] = "deleted"
            return deepcopy(data[object_id])
        raise SandboxError(f"Unsupported sandbox operation: {tool}", "NOT_IMPLEMENTED")

    def _tool_cancel_subscription(self, args: dict[str, Any]) -> dict[str, Any]:
        subscription_id = args.get("subscription_id") or args.get("id")
        subscriptions = self._collection("subscriptions")
        if subscription_id not in subscriptions:
            raise SandboxError("Subscription not found", "NOT_FOUND")
        at_period_end = args.get("at_period_end")
        if not isinstance(at_period_end, bool):
            raise SandboxError("at_period_end is required and must be boolean", "VALIDATION_ERROR")
        subscriptions[subscription_id]["cancel_at_period_end"] = at_period_end
        subscriptions[subscription_id]["status"] = "active" if at_period_end else "cancelled"
        return deepcopy(subscriptions[subscription_id])

    def _tool_refund_order(self, args: dict[str, Any]) -> dict[str, Any]:
        order_id = args.get("order_id") or args.get("id")
        orders = self._collection("orders")
        if order_id not in orders:
            raise SandboxError("Order not found", "NOT_FOUND")
        orders[order_id]["refunded"] = True
        refund = {
            "id": f"ref_{order_id}",
            "order_id": order_id,
            "amount": orders[order_id]["total"],
        }
        self._collection("refunds")[refund["id"]] = refund
        return deepcopy(refund)

    def _tool_refund_invoice(self, args: dict[str, Any]) -> dict[str, Any]:
        invoice_id = args.get("invoice_id") or args.get("id")
        invoices = self._collection("invoices")
        if invoice_id not in invoices:
            raise SandboxError("Invoice not found", "NOT_FOUND")
        if invoices[invoice_id].get("status") != "paid":
            raise SandboxError("Only paid invoices can be refunded", "INVALID_STATE")
        refund = {
            "id": f"ref_{invoice_id}",
            "invoice_id": invoice_id,
            "amount": invoices[invoice_id]["amount"],
        }
        self._collection("refunds")[refund["id"]] = refund
        invoices[invoice_id]["status"] = "refunded"
        return deepcopy(refund)

    def _tool_terminate_account(self, args: dict[str, Any]) -> dict[str, Any]:
        customer_id = args.get("customer_id") or args.get("id")
        customers = self._collection("customers")
        if customer_id not in customers:
            raise SandboxError("Billing account not found", "NOT_FOUND")
        customers[customer_id]["status"] = "terminated"
        for subscription in self._collection("subscriptions").values():
            if subscription.get("customer_id") == customer_id:
                subscription["status"] = "cancelled"
        return deepcopy(customers[customer_id])

    def _tool_assign_opportunity(self, args: dict[str, Any]) -> dict[str, Any]:
        opportunity_id = args.get("opportunity_id") or args.get("id")
        owner_id = args.get("owner_id")
        opportunities = self._collection("opportunities")
        if opportunity_id not in opportunities or owner_id not in self._collection("owners"):
            raise SandboxError("Opportunity or owner not found", "NOT_FOUND")
        opportunities[opportunity_id]["owner_id"] = owner_id
        return deepcopy(opportunities[opportunity_id])


def create_sandbox(domain: str) -> StatefulSandbox:
    return StatefulSandbox(domain if domain in INITIAL_STATES else "generic")
