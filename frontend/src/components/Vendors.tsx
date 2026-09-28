import { useEffect, useState } from "react";
import { api, type Memory, type Vendor } from "../api";
import { Markdown, MemoryCard, Spinner } from "./ui";

export default function Vendors({ version }: { version: number }) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    api.vendors().then((v) => {
      setVendors(v);
      setSel((s) => s ?? v[0]?.id ?? null);
    });
  }, [version]);

  return (
    <div className="vendors-layout">
      <aside className="vendor-list">
        {vendors.map((v) => (
          <button key={v.id} className={sel === v.id ? "selected" : ""} onClick={() => setSel(v.id)}>
            <div className="vendor">{v.name}</div>
            <div className="muted small">
              {v.id} · {v.city} · {v.category} · {v.decided}/{v.invoices} decided
            </div>
          </button>
        ))}
      </aside>
      <section className="detail">
        {sel && <VendorProfile key={`${sel}-${version}`} vendor={vendors.find((v) => v.id === sel)!} />}
      </section>
    </div>
  );
}

function VendorProfile({ vendor }: { vendor: Vendor }) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [profile, setProfile] = useState<string | null>(null);
  const [backend, setBackend] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.vendorMemories(vendor.id).then(setMemories).catch((e) => setError(e.message));
  }, [vendor.id]);

  const reflect = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.vendorProfile(vendor.id);
      setProfile(r.profile);
      setBackend(r.backend);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="invoice">
      <div className="inv-header">
        <div>
          <h2>{vendor.name}</h2>
          <div className="muted small">
            GSTIN {vendor.gstin} · {vendor.city} (state {vendor.state_code}) · {vendor.payment_terms}
          </div>
        </div>
      </div>

      <div className="section">
        <div className="section-head">
          <h3>Vendor profile (reflect)</h3>
          <button className="primary" onClick={reflect} disabled={loading || !memories?.length}>
            {loading ? <><Spinner /> Reflecting over memories…</> : profile ? "Rebuild profile" : "Build profile from memory"}
          </button>
        </div>
        {error && <div className="banner error">{error}</div>}
        {profile ? (
          <div className="profile">
            <Markdown text={profile} />
            <div className="muted small">Synthesised by {backend === "hindsight" ? "Hindsight reflect" : "local reflect (Groq over stored memories)"}.</div>
          </div>
        ) : (
          <p className="muted">
            Reflect reasons over everything the bank remembers about this vendor and writes a handling guide.
          </p>
        )}
      </div>

      <div className="section">
        <h3>What LedgerLens remembers {memories && <span className="count">{memories.length}</span>}</h3>
        {!memories ? <Spinner /> : memories.length === 0 ? (
          <p className="muted">Nothing yet. Decide one of this vendor's invoices, seed history or run a replay.</p>
        ) : (
          <div className="memories">
            {[...memories].sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? "")).map((m) => (
              <MemoryCard key={m.id} m={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
