import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// Katalog id dan en sejak hari pertama (ADR-019). Bahasa awal mengikuti bahasa sistem.
const resources = {
  id: {
    translation: {
      title: "Recap (kerangka spike S8)",
      sidecar: "Sidecar",
      state: "Status",
      states: { init: "memulai", starting: "menjalankan", running: "berjalan", exited: "berhenti", restarting: "memulai ulang", failed: "gagal", stopped: "dihentikan" },
      restarts: "Restart",
      rtt: "Waktu jawab ping",
      frames: "Frame audio diterima",
      lastEvent: "Kejadian terakhir",
      crash: "Simulasikan crash",
      stall: "Simulasikan macet",
      version: "Versi",
      startup: "Waktu startup",
      checkUpdate: "Cek pembaruan",
      updateNone: "Sudah versi terbaru.",
      updateFound: "Pembaruan {{version}} ditemukan, mengunduh…",
      updateError: "Gagal memeriksa pembaruan: {{message}}",
    },
  },
  en: {
    translation: {
      title: "Recap (S8 skeleton spike)",
      sidecar: "Sidecar",
      state: "State",
      states: { init: "initializing", starting: "starting", running: "running", exited: "exited", restarting: "restarting", failed: "failed", stopped: "stopped" },
      restarts: "Restarts",
      rtt: "Ping round trip",
      frames: "Audio frames received",
      lastEvent: "Last event",
      crash: "Simulate crash",
      stall: "Simulate stall",
      version: "Version",
      startup: "Startup time",
      checkUpdate: "Check for updates",
      updateNone: "You are up to date.",
      updateFound: "Update {{version}} found, downloading…",
      updateError: "Update check failed: {{message}}",
    },
  },
};

i18n.use(initReactI18next).init({
  resources,
  lng: navigator.language.toLowerCase().startsWith("id") ? "id" : "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;
