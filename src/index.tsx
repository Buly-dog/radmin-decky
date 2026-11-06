import { ButtonItem, PanelSection, PanelSectionRow, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { FaNetworkWired } from "react-icons/fa";

type Status = {
  installed: boolean; configured: boolean; state: string; ready: boolean;
  ip: string; message: string; enabled: boolean; installing: boolean; install_failed: boolean; gui_mode: boolean;
};
const getStatus = callable<[], Status>("get_status");
const setEnabled = callable<[enabled: boolean], Status>("set_enabled");
const restart = callable<[], Status>("restart");
const getLogs = callable<[], string>("get_logs");
const installSystem = callable<[], Status>("install_system");
const setGuiMode = callable<[enabled: boolean], Status>("set_gui_mode");

function Content() {
  const [status, setStatus] = useState<Status>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [logs, setLogs] = useState<string | null>(null);
  const alive = useRef(true);
  const refreshing = useRef(false);
  const actionRunning = useRef(false);
  const actionEpoch = useRef(0);
  const refresh = useCallback(async () => {
    if (refreshing.current || actionRunning.current) return;
    refreshing.current = true;
    const epoch = actionEpoch.current;
    try {
      const next = await getStatus();
      if (alive.current && epoch === actionEpoch.current) { setStatus(next); setPollError(""); }
    } catch (e) {
      if (alive.current && epoch === actionEpoch.current) setPollError(String(e));
    } finally { refreshing.current = false; }
  }, []);
  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 3000);
    return () => { alive.current = false; clearInterval(timer); };
  }, [refresh]);

  const act = async (action: () => Promise<Status>) => {
    if (actionRunning.current) return;
    actionRunning.current = true;
    actionEpoch.current++;
    setBusy(true); setError("");
    try {
      const next = await action();
      if (alive.current) setStatus(next);
    } catch (e) {
      const message = String(e);
      if (alive.current) setError(message);
      toaster.toast({ title: "Radmin VPN", body: message });
    } finally { actionRunning.current = false; if (alive.current) setBusy(false); }
  };
  return <>
    {status && !status.installed && <PanelSection title="Первый запуск">
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || status.installing}
        onClick={() => { void act(installSystem); }}>
        {status.installing ? "Устанавливается…" : status.install_failed ? "Повторить установку компонентов" : "Установить компоненты VPN"}
      </ButtonItem></PanelSectionRow>
      <PanelSectionRow><div style={{fontSize: 12, padding: "8px 0"}}>Загрузка около 178 МБ. Не выключайте Deck и не удаляйте плагин до завершения.</div></PanelSectionRow>
    </PanelSection>}
    <PanelSection title="Подключение">
      <PanelSectionRow>
        <ToggleField label="Radmin VPN" description="Запустить VPN в фоне"
          checked={status?.enabled ?? false}
          disabled={busy || !status?.installed || !status?.configured || status.state === "deactivating"}
          onChange={(value) => { void act(() => setEnabled(value)); }} />
      </PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: 14, padding: "8px 0", lineHeight: 1.5 }}>
        {busy ? "Выполняется команда…" : status?.message ?? "Проверяю состояние…"}
        {status?.ready && <div style={{ color: "#8be2b1" }}>VPN IP: {status.ip}</div>}
        <div style={{ opacity: 0.65, fontSize: 12 }}>Статус связи с друзьями пока не определяется.</div>
        {(error || pollError) && <div style={{ color: "#ffb4ab", overflowWrap: "anywhere" }}>{error || pollError}</div>}
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !status?.enabled}
        onClick={() => { void act(restart); }}>Перезапустить VPN</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" onClick={() => { void refresh(); }}>Обновить статус</ButtonItem></PanelSectionRow>
    </PanelSection>
    <PanelSection title="Режим запуска">
      <PanelSectionRow><ToggleField label="Запуск с окном Radmin"
        description="Открывает окно Radmin в игровом режиме. Для отключения VPN используйте переключатель плагина."
        checked={status?.gui_mode ?? false}
        disabled={busy || !status?.installed || status.enabled || status.state === "deactivating"}
        onChange={(value) => { void act(() => setGuiMode(value)); }} />
      </PanelSectionRow>
    </PanelSection>
    <PanelSection title="Диагностика">
      <PanelSectionRow><ButtonItem layout="below" onClick={async () => {
        if (logs !== null) { setLogs(null); return; }
        try { const text = await getLogs(); if (alive.current) setLogs(text); }
        catch (e) { if (alive.current) setError(String(e)); }
      }}>{logs === null ? "Показать журнал" : "Скрыть журнал"}</ButtonItem></PanelSectionRow>
      {logs !== null && <PanelSectionRow><ButtonItem layout="below" onClick={async () => {
        try { const text = await getLogs(); if (alive.current) setLogs(text); }
        catch (e) { if (alive.current) setError(String(e)); }
      }}>Обновить журнал</ButtonItem></PanelSectionRow>}
      {logs !== null && <PanelSectionRow><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 11, maxHeight: 340, overflowY: "auto" }}>{logs}</pre></PanelSectionRow>}
    </PanelSection>
  </>;
}
export default definePlugin(() => ({
  name: "Radmin VPN",
  titleView: <div className={staticClasses.Title}>Radmin VPN</div>,
  content: <Content />,
  icon: <FaNetworkWired />,
  onDismount() {},
}));
