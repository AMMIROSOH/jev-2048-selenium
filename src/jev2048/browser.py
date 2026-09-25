from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from .board import Board, Direction, make_board

BrowserName = Literal["chrome", "edge", "firefox"]


@dataclass(frozen=True)
class GameStatus:
    won: bool
    over: bool


KEYS: dict[Direction, str] = {
    "up": Keys.ARROW_UP,
    "right": Keys.ARROW_RIGHT,
    "down": Keys.ARROW_DOWN,
    "left": Keys.ARROW_LEFT,
}


class GameBrowser:
    URL = "https://www.2048.org/"

    def __init__(
        self,
        browser: BrowserName = "chrome",
        headless: bool = False,
        window_width: int = 1100,
        window_height: int = 1000,
        app_mode: bool = False,
    ) -> None:
        window_size = f"--window-size={window_width},{window_height}"
        if browser == "chrome":
            options = webdriver.ChromeOptions()
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-infobars")
            if headless:
                options.add_argument("--headless=new")
            if app_mode:
                options.add_argument(f"--app={self.URL}")
                options.add_argument("--disable-gpu")
            options.add_argument(window_size)
            options.add_argument("--disable-notifications")
            self.driver = webdriver.Chrome(options=options)
        elif browser == "edge":
            options = webdriver.EdgeOptions()
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-infobars")
            if headless:
                options.add_argument("--headless=new")
            if app_mode:
                options.add_argument(f"--app={self.URL}")
                options.add_argument("--disable-gpu")
            options.add_argument(window_size)
            options.add_argument("--disable-notifications")
            self.driver = webdriver.Edge(options=options)
        elif browser == "firefox":
            options = webdriver.FirefoxOptions()
            if headless:
                options.add_argument("-headless")
            self.driver = webdriver.Firefox(options=options)
            self.driver.set_window_size(window_width, window_height)
        else:
            raise ValueError(f"Unsupported browser: {browser}")

    def open(self) -> None:
        self.driver.get(self.URL)
        WebDriverWait(self.driver, 20).until(lambda driver: len(driver.find_elements(By.CSS_SELECTOR, ".tile")) >= 2)

    def set_viewport_size(self, width: int, height: int) -> None:
        """Resize the outer window until the page viewport has the requested size."""
        self.driver.set_window_position(20, 20)
        for _ in range(3):
            inner_width, inner_height = self.driver.execute_script("return [window.innerWidth, window.innerHeight]")
            outer = self.driver.get_window_size()
            delta_width = int(width) - int(inner_width)
            delta_height = int(height) - int(inner_height)
            if delta_width == 0 and delta_height == 0:
                break
            self.driver.set_window_size(outer["width"] + delta_width, outer["height"] + delta_height)
            time.sleep(0.15)

    def close(self) -> None:
        self.driver.quit()

    def new_game(self) -> None:
        old = self.read_board()
        self.driver.find_element(By.CSS_SELECTOR, ".restart-button").click()
        WebDriverWait(self.driver, 5).until(lambda _: self.read_board() != old or self.read_score() == 0)

    def continue_after_win(self) -> None:
        self.driver.find_element(By.CSS_SELECTOR, ".keep-playing-button").click()
        WebDriverWait(self.driver, 3).until(lambda _: not self.status().won)

    def status(self) -> GameStatus:
        classes = self.driver.find_element(By.CSS_SELECTOR, ".game-message").get_attribute("class") or ""
        return GameStatus(won="game-won" in classes, over="game-over" in classes)

    def read_score(self) -> int:
        score = self.driver.execute_script(
            "const raw = window.localStorage.getItem('gameState'); "
            "if (!raw) return null; "
            "try { return JSON.parse(raw).score ?? null; } catch { return null; }"
        )
        if score is not None:
            return int(score)
        # Selenium's .text is empty when the site's heading is hidden by the
        # recording layout. textContent still exposes its final score.
        text = self.driver.find_element(By.CSS_SELECTOR, ".score-container").get_attribute("textContent") or ""
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else 0

    def read_board(self) -> Board:
        stored = self.driver.execute_script(
            """
            const raw = window.localStorage.getItem('gameState');
            if (!raw) return null;
            const state = JSON.parse(raw);
            const rows = Array.from({length: 4}, () => Array(4).fill(0));
            for (let x = 0; x < 4; x++) {
              for (let y = 0; y < 4; y++) {
                const tile = state.grid.cells[x][y];
                rows[y][x] = tile ? tile.value : 0;
              }
            }
            return rows;
            """
        )
        if stored is not None:
            return make_board(stored)

        # The site clears saved state at game-over. Read the rendered board then.
        rows = [[0] * 4 for _ in range(4)]
        for element in self.driver.find_elements(By.CSS_SELECTOR, ".tile"):
            classes = element.get_attribute("class") or ""
            position = re.search(r"tile-position-(\d)-(\d)", classes)
            value = re.search(r"tile-(\d+)", classes)
            if position and value:
                column, row = int(position.group(1)) - 1, int(position.group(2)) - 1
                rows[row][column] = int(value.group(1))
        return make_board(rows)

    def send_move(self, direction: Direction, old_board: Board, timeout: float = 3.0) -> Board:
        self.driver.find_element(By.TAG_NAME, "body").send_keys(KEYS[direction])
        try:
            WebDriverWait(self.driver, timeout, poll_frequency=0.03).until(
                lambda _: self.read_board() != old_board or self.status().over
            )
        except TimeoutException as error:
            raise RuntimeError(f"The website did not apply legal move {direction!r}") from error
        return self.read_board()

    def pause(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def inject_recording_ui(self, mode: str) -> None:
        self.driver.execute_script(
            r"""
            if (document.getElementById('jev-recording-stage')) return;
            document.title = 'Jev 2048 Recording';

            const style = document.createElement('style');
            style.id = 'jev-recording-style';
            style.textContent = `
              :root {
                --jev-bg: #090d18;
                --jev-panel: rgba(20, 27, 45, .92);
                --jev-panel-2: rgba(30, 39, 62, .82);
                --jev-text: #f8fafc;
                --jev-muted: #91a0ba;
                --jev-gold: #f6c453;
                --jev-orange: #f59e42;
                --jev-green: #45d6a1;
                --jev-blue: #68a7ff;
              }
              html, body { min-width: 0 !important; min-height: 100% !important; }
              body {
                margin: 0 !important;
                overflow: hidden !important;
                background:
                  radial-gradient(circle at 50% 19%, rgba(246,196,83,.15), transparent 27%),
                  radial-gradient(circle at 15% 78%, rgba(104,167,255,.12), transparent 30%),
                  linear-gradient(160deg, #10182a 0%, var(--jev-bg) 48%, #070a12 100%) !important;
                color: var(--jev-text) !important;
              }
              body > :not(#jev-recording-stage):not(#jev-countdown):not(script):not(style) { display: none !important; }
              #jev-recording-stage {
                width: 100vw;
                height: 100vh;
                box-sizing: border-box;
                padding: 5.5vh 7vw 4vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 2.25vh;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
                position: relative;
                isolation: isolate;
              }
              #jev-recording-stage::before {
                content: '';
                position: absolute;
                inset: 2.2vh 4vw;
                border: 1px solid rgba(255,255,255,.055);
                border-radius: 42px;
                pointer-events: none;
                z-index: -1;
              }
              #jev-hero { width: min(860px, 86vw); }
              #jev-live-row { display: flex; align-items: center; justify-content: space-between; }
              #jev-live {
                display: flex; align-items: center; gap: 11px; color: var(--jev-green);
                font-size: 17px; font-weight: 800; letter-spacing: .18em;
              }
              #jev-live-dot {
                width: 13px; height: 13px; border-radius: 999px; background: var(--jev-green);
                box-shadow: 0 0 0 6px rgba(69,214,161,.12), 0 0 22px rgba(69,214,161,.7);
                animation: jevPulse 1.5s ease-in-out infinite;
              }
              #jev-brand-mini { color: var(--jev-muted); font-size: 16px; font-weight: 700; letter-spacing: .12em; }
              #jev-title {
                margin: 14px 0 2px; font-size: clamp(52px, 7vw, 76px); line-height: .96;
                font-weight: 950; letter-spacing: -.055em;
              }
              #jev-title span {
                background: linear-gradient(95deg, var(--jev-gold), #ff9f57);
                -webkit-background-clip: text; background-clip: text; color: transparent;
              }
              #jev-subtitle { color: var(--jev-muted); font-size: 20px; font-weight: 600; margin-top: 10px; }
              #jev-summary {
                width: min(860px, 86vw); display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
              }
              .jev-summary-card {
                background: rgba(255,255,255,.055); border: 1px solid rgba(255,255,255,.08);
                border-radius: 19px; padding: 15px 22px; backdrop-filter: blur(14px);
              }
              .jev-summary-label { color: var(--jev-muted); font-size: 13px; font-weight: 800; letter-spacing: .14em; }
              .jev-summary-value { margin-top: 3px; color: var(--jev-text); font-size: 31px; font-weight: 900; }
              #jev-recording-stage > .container {
                width: 500px !important; margin: 0 !important; flex: 0 0 auto;
                filter: drop-shadow(0 28px 44px rgba(0,0,0,.34));
              }
              #jev-recording-stage .container > .heading,
              #jev-recording-stage .container > .above-game,
              #jev-recording-stage .container > .game-explanation,
              #jev-recording-stage .container > hr { display: none !important; }
              #jev-recording-stage .game-container { margin-top: 0 !important; }
              #jev-dashboard {
                width: min(860px, 86vw); box-sizing: border-box; padding: 25px 27px;
                background: linear-gradient(145deg, var(--jev-panel), rgba(12,17,30,.95));
                border: 1px solid rgba(255,255,255,.09); border-radius: 28px;
                box-shadow: 0 22px 60px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.05);
                display: grid; grid-template-columns: .86fr 1.14fr; gap: 29px;
              }
              #jev-decision { display: flex; flex-direction: column; min-width: 0; }
              .jev-kicker { color: var(--jev-muted); font-size: 13px; font-weight: 850; letter-spacing: .15em; }
              #jev-choice-row { display: flex; align-items: center; gap: 17px; margin: 9px 0 12px; }
              #jev-arrow {
                width: 70px; height: 70px; display: grid; place-items: center; border-radius: 20px;
                color: #171109; background: linear-gradient(145deg, var(--jev-gold), var(--jev-orange));
                box-shadow: 0 12px 28px rgba(245,158,66,.25); font-size: 52px; font-weight: 900;
              }
              #jev-choice { font-size: 38px; line-height: 1; font-weight: 950; letter-spacing: -.03em; }
              #jev-status { color: var(--jev-green); font-size: 14px; font-weight: 850; letter-spacing: .07em; }
              #jev-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; margin-top: 16px; }
              .jev-metric { background: var(--jev-panel-2); border-radius: 12px; padding: 10px; }
              .jev-metric strong { display: block; font-size: 17px; }
              .jev-metric span { color: var(--jev-muted); font-size: 11px; font-weight: 750; }
              #jev-bars { display: flex; flex-direction: column; gap: 9px; }
              .jev-bar-row { display: grid; grid-template-columns: 58px 1fr 52px; align-items: center; gap: 10px; }
              .jev-bar-name { font-size: 13px; color: #dbe3f1; font-weight: 850; }
              .jev-bar-track { height: 10px; border-radius: 99px; background: rgba(255,255,255,.07); overflow: hidden; }
              .jev-bar-fill {
                height: 100%; width: 0%; border-radius: inherit;
                background: linear-gradient(90deg, var(--jev-blue), #a78bfa); transition: width .38s ease;
              }
              .jev-bar-row.is-selected .jev-bar-fill { background: linear-gradient(90deg, var(--jev-gold), var(--jev-orange)); }
              .jev-bar-percent { color: var(--jev-muted); text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; }
              #jev-confidence-row { display: flex; justify-content: space-between; margin-top: 13px; color: var(--jev-muted); font-size: 13px; }
              #jev-confidence { color: var(--jev-text); font-weight: 850; }
              #jev-history { margin-top: 14px; display: flex; align-items: center; gap: 7px; min-height: 31px; }
              .jev-history-item {
                width: 31px; height: 31px; display: grid; place-items: center; border-radius: 9px;
                background: rgba(255,255,255,.065); color: #cbd5e1; font-size: 21px; font-weight: 850;
              }
              #jev-footer {
                width: min(860px, 86vw); display: flex; justify-content: space-between;
                color: #65728a; font-size: 13px; font-weight: 750; letter-spacing: .08em;
              }
              #jev-countdown {
                display: none; position: fixed; inset: 0; z-index: 10000; place-items: center;
                color: white; font-size: 220px; font-weight: 950; background: rgba(6,9,16,.82);
                backdrop-filter: blur(12px);
              }
              @media (max-width: 700px) {
                #jev-recording-stage { padding: 90px 16px 18px; gap: 10px; }
                #jev-recording-stage::before { inset: 10px; border-radius: 24px; }
                #jev-hero, #jev-summary, #jev-dashboard, #jev-footer { width: min(508px, 94vw); }
                #jev-live { font-size: 10px; gap: 7px; }
                #jev-live-dot { width: 8px; height: 8px; box-shadow: 0 0 0 4px rgba(69,214,161,.12); }
                #jev-brand-mini { font-size: 10px; }
                #jev-title { margin: 7px 0 1px; font-size: 42px; }
                #jev-subtitle { margin-top: 5px; font-size: 12px; }
                #jev-summary { gap: 8px; }
                .jev-summary-card { border-radius: 12px; padding: 8px 12px; }
                .jev-summary-label { font-size: 8px; }
                .jev-summary-value { font-size: 21px; }
                #jev-recording-stage > .container { zoom: .78; }
                #jev-dashboard { padding: 14px 15px; border-radius: 18px; grid-template-columns: .9fr 1.1fr; gap: 16px; }
                .jev-kicker { font-size: 8px; }
                #jev-choice-row { gap: 9px; margin: 5px 0 7px; }
                #jev-arrow { width: 43px; height: 43px; border-radius: 12px; }
                #jev-arrow svg { width: 28px; height: 28px; }
                #jev-choice { font-size: 23px; }
                #jev-status { margin-top: 3px; font-size: 8px; letter-spacing: .03em; }
                #jev-metrics { gap: 5px; margin-top: 8px; }
                .jev-metric { border-radius: 8px; padding: 6px; }
                .jev-metric strong { font-size: 11px; }
                .jev-metric span { font-size: 7px; }
                #jev-bars { gap: 5px; }
                .jev-bar-row { grid-template-columns: 38px 1fr 31px; gap: 6px; }
                .jev-bar-name { font-size: 8px; }
                .jev-bar-track { height: 7px; }
                .jev-bar-percent { font-size: 8px; }
                #jev-confidence-row { margin-top: 7px; font-size: 8px; }
                #jev-history { margin-top: 7px; gap: 4px; min-height: 19px; }
                .jev-history-item { width: 19px; height: 19px; border-radius: 5px; font-size: 13px; }
                #jev-footer { font-size: 8px; }
                #jev-countdown { font-size: 125px; }
              }
              @keyframes jevPulse { 50% { opacity: .55; transform: scale(.86); } }
              @keyframes jevDecision { 0% { transform: scale(.92); } 65% { transform: scale(1.08); } 100% { transform: scale(1); } }
              .jev-pop { animation: jevDecision .34s ease-out; }
            `;
            document.head.appendChild(style);

            const original = document.querySelector('.container');
            const stage = document.createElement('main');
            stage.id = 'jev-recording-stage';
            stage.innerHTML = `
              <section id="jev-hero">
                <div id="jev-live-row"><div id="jev-live"><i id="jev-live-dot"></i> LIVE DECISION ENGINE</div><div id="jev-brand-mini">JEV × 2048</div></div>
                <h1 id="jev-title">JEV PLAYS <span>2048</span></h1>
                <div id="jev-subtitle">Expectimax search guided by calibrated Jev decisions</div>
              </section>
              <section id="jev-summary">
                <div class="jev-summary-card"><div class="jev-summary-label">SCORE</div><div class="jev-summary-value" id="jev-score">0</div></div>
                <div class="jev-summary-card"><div class="jev-summary-label">MAX TILE</div><div class="jev-summary-value" id="jev-max">2</div></div>
                <div class="jev-summary-card"><div class="jev-summary-label">MOVE</div><div class="jev-summary-value" id="jev-move">#0</div></div>
              </section>
            `;
            document.body.appendChild(stage);
            stage.appendChild(original);

            const dashboard = document.createElement('section');
            dashboard.id = 'jev-dashboard';
            dashboard.innerHTML = `
              <div id="jev-decision">
                <div class="jev-kicker">NEXT DECISION</div>
                <div id="jev-choice-row"><div id="jev-arrow"></div><div><div id="jev-choice">READY</div><div id="jev-status">WAITING FOR FIRST MOVE</div></div></div>
                <div id="jev-metrics">
                  <div class="jev-metric"><strong id="jev-depth">—</strong><span>DEPTH</span></div>
                  <div class="jev-metric"><strong id="jev-nodes">—</strong><span>NODES</span></div>
                  <div class="jev-metric"><strong id="jev-time">—</strong><span>SEARCH</span></div>
                </div>
              </div>
              <div>
                <div class="jev-kicker" style="margin-bottom:11px">FUSED MOVE PROBABILITY</div>
                <div id="jev-bars">
                  ${['up','right','down','left'].map(d => `<div class="jev-bar-row" data-direction="${d}"><div class="jev-bar-name">${d.toUpperCase()}</div><div class="jev-bar-track"><div class="jev-bar-fill"></div></div><div class="jev-bar-percent">0%</div></div>`).join('')}
                </div>
                <div id="jev-confidence-row"><span>JEV CONFIDENCE</span><strong id="jev-confidence">—</strong></div>
                <div id="jev-history"></div>
              </div>
            `;
            stage.appendChild(dashboard);

            const footer = document.createElement('footer');
            footer.id = 'jev-footer';
            footer.innerHTML = `<span>2048.ORG • SELENIUM</span><span id="jev-mode">${String(arguments[0]).toUpperCase()} MODE</span>`;
            stage.appendChild(footer);

            const countdown = document.createElement('div');
            countdown.id = 'jev-countdown';
            document.body.appendChild(countdown);
            """,
            mode,
        )

    def update_recording_ui(self, stats: dict[str, object]) -> None:
        self.driver.execute_script(
            r"""
            const s = arguments[0];
            if (!document.getElementById('jev-recording-stage')) return;
            const arrows = {up:'↑', right:'→', down:'↓', left:'←'};
            const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
            set('jev-score', Number(s.score || 0).toLocaleString());
            set('jev-max', Number(s.max_tile || 0).toLocaleString());
            set('jev-move', '#' + String(s.move_number || 0));
            set('jev-choice', String(s.direction || 'ready').toUpperCase());
            set('jev-status', s.status || 'DECISION READY');
            set('jev-depth', s.depth ?? '—');
            set('jev-nodes', Number(s.nodes || 0).toLocaleString());
            set('jev-time', s.search_ms == null ? '—' : Number(s.search_ms).toFixed(0) + 'ms');
            set('jev-confidence', s.jev_confidence == null ? 'SEARCH ONLY' : Math.round(Number(s.jev_confidence) * 100) + '%');

            const arrow = document.getElementById('jev-arrow');
            if (arrow) {
              const rotation = {up: 0, right: 90, down: 180, left: 270}[s.direction];
              arrow.innerHTML = rotation == null ? '—' :
                `<svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" style="display:block;transform:rotate(${rotation}deg)"><path d="M24 40V8 M11 21L24 8l13 13" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
              arrow.classList.remove('jev-pop'); void arrow.offsetWidth; arrow.classList.add('jev-pop');
            }
            const probabilities = s.probabilities || {};
            document.querySelectorAll('.jev-bar-row').forEach(row => {
              const direction = row.dataset.direction;
              const probability = Math.max(0, Math.min(1, Number(probabilities[direction] || 0)));
              row.querySelector('.jev-bar-fill').style.width = (probability * 100).toFixed(1) + '%';
              row.querySelector('.jev-bar-percent').textContent = Math.round(probability * 100) + '%';
              row.classList.toggle('is-selected', direction === s.direction);
            });
            const history = document.getElementById('jev-history');
            if (history) {
              history.innerHTML = '<span class="jev-kicker" style="margin-right:4px">RECENT</span>' +
                (s.history || []).map(d => `<span class="jev-history-item">${arrows[d] || '•'}</span>`).join('');
            }
            """,
            stats,
        )

    def update_recording_board_stats(self, score: int, max_tile: int) -> None:
        """Refresh the scoreboard after a move without resetting its decision panel."""
        self.driver.execute_script(
            "document.getElementById('jev-score').textContent = Number(arguments[0]).toLocaleString();"
            "document.getElementById('jev-max').textContent = Number(arguments[1]).toLocaleString();",
            score,
            max_tile,
        )

    def recording_countdown(self, seconds: int) -> None:
        for remaining in range(max(0, seconds), 0, -1):
            self.driver.execute_script(
                "const e=document.getElementById('jev-countdown'); if(e){e.style.display='grid';e.textContent=arguments[0];}",
                remaining,
            )
            time.sleep(1)
        self.driver.execute_script(
            "const e=document.getElementById('jev-countdown'); if(e){e.textContent='GO';setTimeout(()=>e.style.display='none',650);}"
        )
        if seconds:
            time.sleep(0.7)
