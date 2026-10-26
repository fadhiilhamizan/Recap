import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { listen } from "@tauri-apps/api/event";
import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { commands, type AppInfo, type SidecarStatus } from "./bindings";

export default function App() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<SidecarStatus | null>(null);
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [updateMsg, setUpdateMsg] = useState("");

  useEffect(() => {
    // Data selalu berasal dari proses utama; UI hanya menampilkan (dokumen 03 prinsip 4).
    commands.getStatus().then(setStatus);
    commands.uiReady().then(setInfo);
    const unlisten = listen<SidecarStatus>("sidecar-status", (e) => setStatus(e.payload));
    if (import.meta.env.VITE_AUTO_UPDATE === "1") void checkUpdate();
    return () => {
      void unlisten.then((f) => f());
    };
  }, []);

  async function checkUpdate() {
    try {
      const update = await check();
      if (!update) {
        setUpdateMsg(t("updateNone"));
        return;
      }
      setUpdateMsg(t("updateFound", { version: update.version }));
      await update.downloadAndInstall();
      await relaunch();
    } catch (e) {
      setUpdateMsg(t("updateError", { message: String(e) }));
    }
  }

  const state = status?.state ?? "init";
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24, maxWidth: 720 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ fontSize: 20 }}>{t("title")}</h1>
        <select aria-label="Bahasa / Language" value={i18n.language} onChange={(e) => void i18n.changeLanguage(e.target.value)}>
          <option value="id">Bahasa Indonesia</option>
          <option value="en">English</option>
        </select>
      </header>

      <section aria-labelledby="sidecar-heading" style={{ border: "1px solid #ccc", borderRadius: 8, padding: 16 }}>
        <h2 id="sidecar-heading" style={{ fontSize: 16, marginTop: 0 }}>{t("sidecar")}</h2>
        <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 16px", margin: 0 }}>
          <dt>{t("state")}</dt>
          <dd aria-live="polite">{t(`states.${state}`, { defaultValue: state })}{status?.pid ? ` (PID ${status.pid})` : ""}</dd>
          <dt>{t("restarts")}</dt>
          <dd>{status?.restarts ?? 0}</dd>
          <dt>{t("rtt")}</dt>
          <dd>{status?.last_rtt_ms != null ? `${status.last_rtt_ms.toFixed(2)} ms` : "-"}</dd>
          <dt>{t("frames")}</dt>
          <dd>{status?.audio_frames ?? 0}</dd>
          <dt>{t("lastEvent")}</dt>
          <dd>{status?.last_event || "-"}</dd>
        </dl>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={() => void commands.crashSidecar()}>{t("crash")}</button>
          <button onClick={() => void commands.stallSidecar()}>{t("stall")}</button>
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <p>
          {t("version")}: {info?.version ?? "-"} · {t("startup")}: {info?.startup_ms != null ? `${info.startup_ms.toFixed(0)} ms` : "-"}
        </p>
        <button onClick={() => void checkUpdate()}>{t("checkUpdate")}</button>
        <p role="status">{updateMsg}</p>
      </section>
    </main>
  );
}
