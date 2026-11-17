import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test-utils";
import { SchemaForm, schemaDefaults, schemaFields, type ConfigValue, type JsonSchema, type SecretState } from "./SchemaForm";

const SCHEMA: JsonSchema = {
  type: "object",
  properties: {
    label: { type: "string", title: "Label", minLength: 1, maxLength: 100, default: "demo" },
    interval_seconds: { type: "integer", title: "Interval (seconds)", minimum: 1, maximum: 3600, default: 30 },
    enabled_feature: { type: "boolean", title: "Feature" },
    mode: { type: "string", title: "Mode", enum: ["fast", "slow"] },
    endpoint: { type: "string", title: "Endpoint", format: "uri" },
    token: { type: "string", title: "Token", "x-secret": true },
  },
  required: ["token"],
};

/** Keeps the value in state like the real form does and reports every change. */
function Harness({ schema = SCHEMA, initial = {}, secretState, spy }: { schema?: JsonSchema; initial?: ConfigValue; secretState?: Record<string, SecretState>; spy?: (v: ConfigValue) => void }) {
  const [value, setValue] = useState<ConfigValue>(initial);
  return (
    <SchemaForm
      schema={schema}
      value={value}
      secretState={secretState}
      onChange={(next) => {
        spy?.(next);
        setValue(next);
      }}
    />
  );
}

describe("SchemaForm", () => {
  it("draws every supported kind from the schema", () => {
    renderWithProviders(<Harness />);
    expect(screen.getByRole("textbox", { name: "Label" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Endpoint" })).toHaveAttribute("type", "url");
    expect(screen.getByRole("spinbutton", { name: /Interval/ })).toHaveAttribute("min", "1");
    expect(screen.getByRole("spinbutton", { name: /Interval/ })).toHaveAttribute("max", "3600");
    expect(screen.getByRole("checkbox", { name: "Feature" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Mode" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Token/)).toHaveAttribute("type", "password");
  });

  it("reports typed text, numbers, checkbox and choice", async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    renderWithProviders(<Harness spy={spy} />);
    await user.type(screen.getByRole("textbox", { name: "Label" }), "x");
    expect(spy).toHaveBeenLastCalledWith({ label: "x" });
    await user.type(screen.getByRole("spinbutton", { name: /Interval/ }), "45");
    expect(spy).toHaveBeenLastCalledWith({ label: "x", interval_seconds: 45 });
    await user.click(screen.getByRole("checkbox", { name: "Feature" }));
    expect(spy).toHaveBeenLastCalledWith({ label: "x", interval_seconds: 45, enabled_feature: true });
    await user.selectOptions(screen.getByRole("combobox", { name: "Mode" }), "slow");
    expect(spy).toHaveBeenLastCalledWith({ label: "x", interval_seconds: 45, enabled_feature: true, mode: "slow" });
  });

  it("flags a number outside minimum and maximum before anything is sent", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    const field = screen.getByRole("spinbutton", { name: /Interval/ });
    await user.type(field, "99999");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Zwischen 1 und 3600/)).toBeInTheDocument();
  });

  it("a secret field starts empty and sends nothing while empty", async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    renderWithProviders(<Harness spy={spy} secretState={{ token: "set" }} />);
    const token = screen.getByLabelText(/Token/);
    expect(token).toHaveValue("");
    expect(screen.getByTestId("secret-state-token")).toHaveTextContent("gesetzt");
    await user.type(token, "abc");
    expect(spy).toHaveBeenLastCalledWith({ token: "abc" });
    await user.clear(token);
    // Emptied again: the key is gone, so the stored secret is not overwritten with "".
    expect(spy).toHaveBeenLastCalledWith({});
  });

  it.each<[SecretState | undefined, string]>([
    ["set", "gesetzt"],
    ["unset", "nicht gesetzt"],
    [undefined, "nicht gesetzt"],
    ["reenter", "neu eingeben nötig"],
  ])("shows the state of a stored secret (%s)", (state, text) => {
    renderWithProviders(<Harness secretState={state ? { token: state } : undefined} />);
    expect(screen.getByTestId("secret-state-token")).toHaveTextContent(text);
  });

  it("never prints a secret value it was given", () => {
    renderWithProviders(<Harness initial={{ token: "super-secret-value" }} />);
    expect(screen.getByLabelText(/Token/)).toHaveValue("super-secret-value");
    expect(document.body.textContent).not.toContain("super-secret-value");
  });

  it("says out loud that a kind is not supported instead of dropping the field", () => {
    const schema: JsonSchema = { type: "object", properties: { nested: { type: "object", title: "Nested" }, list: { type: "array" }, ok: { type: "string" } } };
    renderWithProviders(<Harness schema={schema} />);
    expect(screen.getByTestId("unsupported-nested")).toHaveTextContent(/nicht unterstützt/);
    expect(screen.getByTestId("unsupported-list")).toHaveTextContent("array");
    expect(screen.getByRole("textbox", { name: "ok" })).toBeInTheDocument();
  });

  it("says so for a schema without fields", () => {
    renderWithProviders(<Harness schema={{ type: "object", properties: {} }} />);
    expect(screen.getByText("Dieser Typ hat keine Einstellungen.")).toBeInTheDocument();
  });
});

describe("schema helpers", () => {
  it("lists the fields in schema order and marks the required ones", () => {
    const fields = schemaFields(SCHEMA);
    expect(fields.map((f) => f.name)).toEqual(["label", "interval_seconds", "enabled_feature", "mode", "endpoint", "token"]);
    expect(fields.find((f) => f.name === "token")?.required).toBe(true);
    expect(fields.find((f) => f.name === "label")?.required).toBe(false);
  });

  it("takes defaults from the schema and never for a secret", () => {
    expect(schemaDefaults({ ...SCHEMA, properties: { ...(SCHEMA.properties as object), token: { type: "string", "x-secret": true, default: "leak" } } })).toEqual({ label: "demo", interval_seconds: 30 });
  });

  it("copes with a schema that has no properties", () => {
    expect(schemaFields({})).toEqual([]);
    expect(schemaDefaults({})).toEqual({});
  });
});
