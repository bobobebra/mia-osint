use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::Deserialize;
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

#[derive(Default)]
struct CoreProcess(Mutex<Option<CommandChild>>);

#[derive(Deserialize)]
struct Handshake {
    status: String,
    url: Option<String>,
    error: Option<String>,
}

fn valid_mode(mode: &str) -> bool {
    matches!(mode, "discover" | "workbench")
}

fn stop_core(state: &CoreProcess) {
    if let Some(mut child) = state.0.lock().expect("core process lock").take() {
        let _ = child.kill();
    }
}

fn notify_error(app: &AppHandle, message: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let encoded = serde_json::to_string(message).unwrap_or_else(|_| "\"Unknown error\"".into());
        let _ = window.eval(&format!("window.miaError && window.miaError({encoded});"));
    }
}

fn start_core(app: &AppHandle, mode: &str) -> Result<(), String> {
    if !valid_mode(mode) {
        return Err("mode must be discover or workbench".into());
    }

    let state = app.state::<CoreProcess>();
    stop_core(&state);

    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let handshake: PathBuf = env::temp_dir().join(format!("mia-desktop-{}-{stamp}.json", std::process::id()));
    let _ = fs::remove_file(&handshake);

    let sidecar_args = vec![
        "--mode".to_string(),
        mode.to_string(),
        "--port".to_string(),
        "0".to_string(),
        "--handshake".to_string(),
        handshake.to_string_lossy().into_owned(),
    ];
    let sidecar = app
        .shell()
        .sidecar("mia-core")
        .map_err(|error| error.to_string())?
        .args(sidecar_args);
    let (mut events, child) = sidecar.spawn().map_err(|error| error.to_string())?;
    *state.0.lock().expect("core process lock") = Some(child);

    let event_app = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            if let tauri_plugin_shell::process::CommandEvent::Error(message) = event {
                notify_error(&event_app, &format!("MIA Core error: {message}"));
            }
        }
    });

    let ready_app = app.clone();
    let selected_mode = mode.to_string();
    tauri::async_runtime::spawn(async move {
        for _ in 0..240 {
            if let Ok(payload) = fs::read_to_string(&handshake) {
                if let Ok(result) = serde_json::from_str::<Handshake>(&payload) {
                    let _ = fs::remove_file(&handshake);
                    if result.status == "ready" {
                        if let Some(url) = result.url.filter(|value| value.starts_with("http://127.0.0.1:")) {
                            if let Some(window) = ready_app.get_webview_window("main") {
                                let encoded_url = serde_json::to_string(&url).unwrap_or_default();
                                let encoded_mode = serde_json::to_string(&selected_mode).unwrap_or_default();
                                let _ = window.eval(&format!(
                                    "window.miaReady && window.miaReady({encoded_url}, {encoded_mode});"
                                ));
                            }
                            return;
                        }
                    }
                    notify_error(
                        &ready_app,
                        result.error.as_deref().unwrap_or("MIA Core failed to start"),
                    );
                    return;
                }
            }
            tokio::time::sleep(Duration::from_millis(125)).await;
        }
        notify_error(&ready_app, "MIA Core did not start within 30 seconds. Reopen MIA or use the repair option.");
    });

    Ok(())
}

#[tauri::command]
fn launch_mode(app: AppHandle, mode: String) -> Result<(), String> {
    start_core(&app, &mode)
}

#[tauri::command]
fn stop_mode(app: AppHandle) {
    stop_core(&app.state::<CoreProcess>());
}

pub fn run() {
    let requested_mode = env::args()
        .collect::<Vec<_>>()
        .windows(2)
        .find(|pair| pair[0] == "--mode" && valid_mode(&pair[1]))
        .map(|pair| pair[1].clone());

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(CoreProcess::default())
        .invoke_handler(tauri::generate_handler![launch_mode, stop_mode])
        .setup(move |app| {
            if let Some(mode) = requested_mode.as_deref() {
                start_core(app.handle(), mode).map_err(std::io::Error::other)?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build MIA desktop shell");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_core(&handle.state::<CoreProcess>());
        }
    });
}
