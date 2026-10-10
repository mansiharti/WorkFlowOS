// Safe API fetch helper to ensure responses are valid JSON and non-JSON errors are handled gracefully
async function safeFetchJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (netErr) {
    console.error('[API FETCH ERROR]', netErr);
    throw new Error(`Network request failed: ${netErr.message || netErr}`);
  }

  const contentType = response.headers.get('content-type') || '';
  const text = await response.text();

  if (!contentType.includes('application/json')) {
    console.error('[API INVALID CONTENT-TYPE]', { url, status: response.status, contentType, body: text });
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}: Workflow API returned an invalid response.`);
    }
    try {
      return JSON.parse(text);
    } catch (e) {
      throw new Error('Workflow API returned an invalid response.');
    }
  }

  try {
    return JSON.parse(text);
  } catch (parseErr) {
    console.error('[API JSON PARSE ERROR]', { url, status: response.status, parseErr, body: text });
    throw new Error('Workflow API returned an invalid response.');
  }
}

// Requirement 4 & 12: Single source of truth for REAL / SANDBOX mode
window.execution_context = { mode: 'REAL' };
let activeMode = 'real';
let currentTeachWorkflowId = null;
let currentChatPlan = null;
let currentTeachPlan = null;
let currentEvolution = null;
let isTeachingRecording = false;
let currentActiveExecutionId = null;
let currentActiveWorkflowId = null;
let pendingModalWorkflowId = null;

// --- Mode Management ---
function setMode(mode) {
  const normMode = (mode || 'REAL').toUpperCase() === 'SANDBOX' ? 'SANDBOX' : 'REAL';
  window.execution_context.mode = normMode;
  activeMode = normMode.toLowerCase();

  const topModeLabel = document.getElementById('top-mode-indicator');
  const sandboxBtn = document.getElementById('mode-sandbox-btn');
  const realBtn = document.getElementById('mode-real-btn');

  if (normMode === 'REAL') {
    if (topModeLabel) {
      topModeLabel.innerText = 'MODE: REAL';
      topModeLabel.style.color = 'var(--accent-rose)';
    }
    if (sandboxBtn) sandboxBtn.className = 'mode-toggle-btn';
    if (realBtn) realBtn.className = 'mode-toggle-btn active-real';
  } else {
    if (topModeLabel) {
      topModeLabel.innerText = 'MODE: SANDBOX';
      topModeLabel.style.color = '#93c5fd';
    }
    if (sandboxBtn) sandboxBtn.className = 'mode-toggle-btn active-sandbox';
    if (realBtn) realBtn.className = 'mode-toggle-btn';
  }

  const selectEl = document.getElementById('setting-default-mode');
  if (selectEl && selectEl.value !== activeMode) {
    selectEl.value = activeMode;
  }

  const chatPlanModeBadge = document.getElementById('plan-mode-badge');
  if (chatPlanModeBadge) chatPlanModeBadge.innerText = normMode;

  const teachTargetBadge = document.getElementById('teach-target-badge');
  if (teachTargetBadge) {
    if (normMode === 'REAL') {
      teachTargetBadge.innerText = 'TARGET: REAL WINDOWS DESKTOP';
      teachTargetBadge.style.background = 'rgba(245, 158, 11, 0.15)';
      teachTargetBadge.style.color = '#fbbf24';
      teachTargetBadge.style.borderColor = 'rgba(245, 158, 11, 0.35)';
    } else {
      teachTargetBadge.innerText = 'TARGET: ISOLATED SANDBOX';
      teachTargetBadge.style.background = 'rgba(79, 120, 255, 0.15)';
      teachTargetBadge.style.color = '#93c5fd';
      teachTargetBadge.style.borderColor = 'rgba(79, 120, 255, 0.35)';
    }
  }

  const execModeInd = document.getElementById('exec-mode-indicator');
  if (execModeInd) execModeInd.innerText = `MODE: ${normMode}`;
}

function promptEnableRealMode() {
  setMode('REAL');
}

function confirmRealMode() {
  setMode('REAL');
}

// --- Navigation ---
function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));

  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) targetTab.classList.add('active');

  const btnMap = {
    'chat': 0,
    'teach': 1,
    'workflows': 2,
    'activity': 3,
    'settings': 4
  };
  const navBtns = document.querySelectorAll('.nav-btn');
  if (btnMap[tabId] !== undefined && navBtns[btnMap[tabId]]) {
    navBtns[btnMap[tabId]].classList.add('active');
  }

  if (tabId === 'workflows') loadWorkflows();
  if (tabId === 'activity') loadActivityLog();
  if (tabId === 'settings') loadSettings();
}

function updateRecordingBadge(isRec) {
  isTeachingRecording = isRec;
  const badge = document.getElementById('recording-badge');
  const text = document.getElementById('recording-badge-text');
  const teachBtn = document.getElementById('start-teach-btn');

  if (isRec) {
    if (badge) { badge.className = 'rec-badge recording'; }
    if (text) { text.innerText = '🔴 RECORDING DEMONSTRATION [STOP]'; }
    if (teachBtn) {
      teachBtn.innerText = 'Stop Teaching';
      teachBtn.className = 'btn btn-danger';
    }
    const liveBox = document.getElementById('recording-live-box');
    if (liveBox) liveBox.style.display = 'block';
  } else {
    if (badge) { badge.className = 'rec-badge not-rec'; }
    if (text) { text.innerText = '🟢 NOT RECORDING'; }
    if (teachBtn) {
      teachBtn.innerText = 'Start Teaching';
      teachBtn.className = 'btn btn-primary';
    }
    const liveBox = document.getElementById('recording-live-box');
    if (liveBox) liveBox.style.display = 'none';
  }
}

function handleBadgeClick() {
  if (isTeachingRecording) {
    toggleTeaching();
  } else {
    switchTab('teach');
  }
}

// --- Mode 2: Chat to Automation ---
function setChatPrompt(text) {
  const input = document.getElementById('chat-input');
  if (input) input.value = text;
}

async function submitChatGoal() {
  const input = document.getElementById('chat-input');
  const promptText = input ? input.value.trim() : '';
  if (!promptText) return;

  document.getElementById('chat-loading').style.display = 'block';
  document.getElementById('chat-plan-card').style.display = 'none';
  document.getElementById('exec-result-card').style.display = 'none';

  try {
    const data = await safeFetchJson('/api/chat/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: promptText })
    });

    document.getElementById('chat-loading').style.display = 'none';

    if (data.success === false || !data.plan) {
      alert(`Could not generate workflow: ${data.detail || data.error || 'Unknown error'}`);
      return;
    }

    currentChatPlan = data.plan;
    renderChatPlanCard(data.plan);
  } catch (err) {
    document.getElementById('chat-loading').style.display = 'none';
    console.error('[CHAT PLAN ERROR]', err);
    alert(err.message || 'Error communicating with Workflow API.');
  }
}

function formatActionDetails(a) {
  const p = a.params || {};
  if (a.type === 'OPEN_APPLICATION') return `Target: ${p.app_name || p.app || 'App'}`;
  if (a.type === 'OPEN_FOLDER') return `Path: ${p.folder_path || p.path || 'Folder'}`;
  if (a.type === 'OPEN_FILE') return `File: ${p.file_path || p.file || 'File'}`;
  if (a.type === 'CREATE_FOLDER') return `Folder: ${p.folder_name || p.name || 'Folder'}`;
  if (a.type === 'CREATE_FILE') return `File: ${p.file_name || p.name || 'File'} in ${p.folder || 'Folder'}`;
  if (a.type === 'MOVE_FILE') return `File: ${p.file_pattern || p.source || 'File'} → ${p.destination || 'Dest'}`;
  if (a.type === 'RENAME_FILE') return `Rename: ${p.old_name} → ${p.new_name}`;
  if (a.type === 'SEARCH_FILES') return `Pattern: ${p.pattern || '*'} in ${p.folder || '.'}`;
  if (a.type === 'READ_FILE') return `Read: ${p.file_path || p.file}`;
  if (a.type === 'TYPE') return `Type: "${p.text || ''}"`;
  if (a.type === 'CLICK') return `Click: ${p.target || 'Element'}`;
  if (a.type === 'BROWSER_NAVIGATE') return `URL: ${p.url}`;
  return JSON.stringify(p);
}

function renderChatPlanCard(plan) {
  document.getElementById('plan-goal-text').innerText = plan.goal || plan.title || plan.name;
  document.getElementById('plan-risk-badge').innerText = plan.risk || 'LOW';
  document.getElementById('plan-risk-badge').className = `badge badge-${(plan.risk || 'LOW').toLowerCase()}`;
  document.getElementById('plan-conf-badge').innerText = `${Math.round((plan.confidence || 0.85) * 100)}%`;
  document.getElementById('plan-mode-badge').innerText = activeMode.toUpperCase();

  const stepsContainer = document.getElementById('plan-steps-container');
  stepsContainer.innerHTML = (plan.actions || []).map((a, i) => `
    <div class="step-item">
      <div class="step-num">${i + 1}</div>
      <div style="flex: 1;">
        <div style="font-weight: 600;">${a.label || a.type}</div>
        <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${formatActionDetails(a)}</div>
      </div>
      <span class="badge badge-${(a.risk || 'LOW').toLowerCase()}">${a.risk || 'LOW'}</span>
    </div>
  `).join('');

  document.getElementById('chat-plan-card').style.display = 'block';
}

async function approveAndRunChatPlan() {
  if (!currentChatPlan) return;
  const targetMode = activeMode.toUpperCase();
  await runStreamingWorkflowExecution({
    workflow_id: currentChatPlan.id || currentChatPlan.workflow_id,
    actions: currentChatPlan.actions,
    plan: currentChatPlan,
    mode: targetMode,
    source: "chat",
    confirmed_medium: true,
    confirmed_high: true
  }, currentChatPlan.goal || currentChatPlan.title);
}

function editChatWorkflow() {
  const input = document.getElementById('chat-input');
  if (input && currentChatPlan) {
    input.value = currentChatPlan.goal || currentChatPlan.title;
    input.focus();
  }
}

function cancelChatWorkflow() {
  document.getElementById('chat-plan-card').style.display = 'none';
  currentChatPlan = null;
}

// --- Mode 1: Teach by Doing ---
async function toggleTeaching() {
  if (!isTeachingRecording) {
    const res = await safeFetchJson('/api/teach/start', { method: 'POST' });
    if (res.recording_id || res.success || (res.status && res.status.toLowerCase() === "recording")) {
      updateRecordingBadge(true);
      document.getElementById('teach-stream').innerHTML = '<div style="color: #38bdf8;">🔴 Teaching started! Recording desktop actions...</div>';
      startTeachPolling();
    }
  } else {
    const res = await safeFetchJson('/api/teach/stop', { method: 'POST' });
    updateRecordingBadge(false);
    stopTeachPolling();
    if (res.plan) {
      currentTeachPlan = res.plan;
      currentTeachWorkflowId = res.workflow_id || res.plan.workflow_id || res.plan.id;
      currentEvolution = res.evolution_proposal || null;
      renderTeachResultCard(res.plan, res.evolution_proposal, res.recording_id, res.workflow_id);
    }
  }
}

let teachPollInterval = null;
function startTeachPolling() {
  if (teachPollInterval) clearInterval(teachPollInterval);
  teachPollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/teach/status');
      const data = await res.json();
      const countEl = document.getElementById('teach-live-count');
      if (countEl) countEl.innerText = `Actions captured: ${data.actions_count || 0}`;

      const currActionEl = document.getElementById('teach-current-action');
      if (currActionEl && data.current_action) currActionEl.innerText = data.current_action;

      const activeAppEl = document.getElementById('teach-active-app');
      if (activeAppEl && data.active_app) activeAppEl.innerText = data.active_app;

      const streamEl = document.getElementById('teach-stream');
      if (streamEl && data.events && data.events.length > 0) {
        streamEl.innerHTML = data.events.map((e, idx) => `
          <div style="margin-bottom: 0.35rem; color: #e2e8f0;">
            <span style="color: var(--text-muted);">${idx + 1}.</span> 
            <b style="color: #38bdf8;">[${e.semantic_action}]</b> 
            <span style="color: #94a3b8;">${e.app_name ? '(' + e.app_name + ')' : ''}</span> 
            <span>${JSON.stringify(e.details || {})}</span>
          </div>
        `).join('');
        streamEl.scrollTop = streamEl.scrollHeight;
      }
    } catch (e) {}
  }, 1000);
}

function stopTeachPolling() {
  if (teachPollInterval) {
    clearInterval(teachPollInterval);
    teachPollInterval = null;
  }
}

async function simulateTeachDemo(demoType) {
  updateRecordingBadge(true);
  document.getElementById('teach-stream').innerHTML = `<div style="color: #f59e0b;">⚡ Simulating demonstration: ${demoType}...</div>`;

  const res = await safeFetchJson('/api/teach/simulate-demo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ demo_id: demoType })
  });

  updateRecordingBadge(false);
  if (res.plan) {
    currentTeachPlan = res.plan;
    currentTeachWorkflowId = res.workflow_id || res.plan.workflow_id || res.plan.id;
    currentEvolution = res.evolution_proposal || null;
    renderTeachResultCard(res.plan, res.evolution_proposal, res.recording_id, res.workflow_id);
  }
}

function renderTeachResultCard(plan, evolution, recId, wfId) {
  const displayTitle = plan.title || plan.name || plan.goal || "Learned Workflow";
  const finalWfId = wfId || plan.workflow_id || plan.id;
  currentTeachWorkflowId = finalWfId;

  document.getElementById('teach-plan-desc').innerText = displayTitle;
  document.getElementById('teach-plan-ver').innerText = `VERSION ${plan.version || 1}`;

  const idBadge = document.getElementById('teach-wf-id-badge');
  if (idBadge) idBadge.innerText = `ID: #${finalWfId || '--'} | REC: ${recId || 'R001'}`;

  const countBadge = document.getElementById('teach-actions-captured-count');
  if (countBadge) countBadge.innerText = `Actions captured: ${(plan.actions || []).length}`;

  const stepsContainer = document.getElementById('teach-steps-container');
  stepsContainer.innerHTML = (plan.actions || []).map((a, i) => `
    <div class="step-item">
      <div class="step-num">${i + 1}</div>
      <div style="flex: 1;">
        <div style="font-weight: 600;">${a.label || a.type}</div>
        <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${formatActionDetails(a)}</div>
      </div>
      <span class="badge badge-${(a.risk || 'LOW').toLowerCase()}">${a.risk || 'LOW'}</span>
    </div>
  `).join('');

  if (evolution && evolution.has_evolution) {
    const evoBox = document.getElementById('evolution-proposal-box');
    evoBox.style.display = 'block';
    document.getElementById('evolution-summary').innerText = evolution.change_summary || "Workflow steps updated.";
    document.getElementById('diff-old-text').innerText = (evolution.old_actions || []).map(a => a.label || a.type).join(' → ');
    document.getElementById('diff-new-text').innerText = (evolution.new_actions || []).map(a => a.label || a.type).join(' → ');
  } else {
    document.getElementById('evolution-proposal-box').style.display = 'none';
  }

  document.getElementById('teach-result-card').style.display = 'block';
}

async function approveAndRunTeachPlan() {
  if (!currentTeachPlan) return;
  const targetMode = activeMode.toUpperCase();
  const wfId = currentTeachWorkflowId || currentTeachPlan.id || currentTeachPlan.workflow_id;
  const displayTitle = currentTeachPlan.title || currentTeachPlan.name || currentTeachPlan.goal;

  switchTab('chat');
  await runStreamingWorkflowExecution({
    workflow_id: wfId,
    actions: currentTeachPlan.actions,
    plan: currentTeachPlan,
    mode: targetMode,
    source: "teach",
    confirmed_medium: true,
    confirmed_high: true
  }, displayTitle);
}

// --- Common Workflow Execution Engine ---
async function runStreamingWorkflowExecution(payload, goalTitle) {
  const resultCard = document.getElementById('exec-result-card');
  const boxContainer = document.getElementById('exec-box-container');
  const heading = document.getElementById('exec-heading');
  const modeInd = document.getElementById('exec-mode-indicator');
  const goalDisp = document.getElementById('exec-goal-display');
  const stepsSummary = document.getElementById('exec-steps-summary');
  const failureBox = document.getElementById('exec-failure-box');
  const statusWord = document.getElementById('exec-status-word');

  resultCard.style.display = 'block';
  boxContainer.className = 'result-box-success';
  heading.innerText = 'EXECUTING WORKFLOW...';
  heading.style.color = '#93c5fd';
  modeInd.innerText = `MODE: ${(payload.mode || activeMode).toUpperCase()}`;
  goalDisp.innerText = goalTitle || payload.workflow_id || 'Workflow';
  stepsSummary.innerHTML = '<div style="color: var(--text-muted);">Starting execution stream...</div>';
  failureBox.style.display = 'none';
  statusWord.innerText = 'IN PROGRESS';
  statusWord.style.color = '#fbbf24';

  currentActiveWorkflowId = payload.workflow_id;

  try {
    const response = await fetch('/api/workflows/execute-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      let errText = `Server error HTTP ${response.status}`;
      try {
        const errJson = await response.json();
        errText = errJson.detail || errJson.error || errText;
      } catch (e) {}
      throw new Error(errText);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let partial = '';
    let executedSteps = [];
    let isSuccess = false;
    let failedReason = '';
    let failedStepName = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      partial += decoder.decode(value, { stream: true });
      const lines = partial.split('\n');
      partial = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);

          // Handle single JSON object response fallback
          if (!event.event && (event.status || event.success !== undefined)) {
            const statusStr = (event.status || '').toUpperCase();
            isSuccess = event.success || statusStr === 'SUCCESS' || statusStr === 'COMPLETED';
            currentActiveExecutionId = event.execution_id || null;
            if (!isSuccess && event.error) {
              failedReason = typeof event.error === 'object' ? (event.error.message || JSON.stringify(event.error)) : String(event.error);
            }
            const actList = payload.actions || (event.result ? event.result.actions : []);
            if (actList && actList.length > 0) {
              executedSteps = actList.map((a, i) => ({ step: i + 1, label: a.label || a.type, status: isSuccess ? 'SUCCESS' : 'FAILED' }));
            }
            break;
          }

          if (event.event === 'action_completed') {
            executedSteps.push({ step: event.step, label: event.label || event.type, status: 'SUCCESS' });
            stepsSummary.innerHTML = executedSteps.map(s => `
              <div style="display: flex; align-items: center; gap: 0.5rem; color: #34d399;">
                <span>✓ Step ${s.step}: ${s.label}</span>
              </div>
            `).join('');
          } else if (event.event === 'action_failed') {
            failedStepName = event.label || `Step ${event.step}`;
            failedReason = event.error || 'Action failed during execution.';
            executedSteps.push({ step: event.step, label: failedStepName, status: 'FAILED' });
          } else if (event.event === 'workflow_completed' || event.result) {
            const res = event.result || event;
            currentActiveExecutionId = res.execution_id || null;
            if (res.status === 'SUCCESS' || res.success) {
              isSuccess = true;
            } else {
              isSuccess = false;
              if (res.error) failedReason = typeof res.error === 'object' ? (res.error.message || JSON.stringify(res.error)) : String(res.error);
            }
          }
        } catch (err) {}
      }
    }

    if (executedSteps.length > 0) {
      stepsSummary.innerHTML = executedSteps.map(s => `
        <div style="display: flex; align-items: center; gap: 0.5rem; color: ${s.status === 'SUCCESS' ? '#34d399' : '#fb7185'};">
          <span>${s.status === 'SUCCESS' ? '✓' : '✕'} Step ${s.step}: ${s.label}</span>
        </div>
      `).join('');
    }

    if (isSuccess) {
      boxContainer.className = 'result-box-success';
      heading.innerText = 'WORKFLOW COMPLETED';
      heading.style.color = '#34d399';
      statusWord.innerText = 'SUCCESS';
      statusWord.style.color = '#34d399';
    } else {
      boxContainer.className = 'result-box-failed';
      heading.innerText = 'WORKFLOW FAILED';
      heading.style.color = '#fb7185';
      statusWord.innerText = 'FAILED';
      statusWord.style.color = '#fb7185';

      failureBox.style.display = 'block';
      document.getElementById('failed-step-name').innerText = failedStepName || 'Execution Step';
      document.getElementById('failed-step-reason').innerText = failedReason || 'An action failed to complete.';
    }
  } catch (err) {
    console.error('[STREAMING EXECUTION ERROR]', err);
    boxContainer.className = 'result-box-failed';
    heading.innerText = 'WORKFLOW FAILED';
    heading.style.color = '#fb7185';
    statusWord.innerText = 'FAILED';
    statusWord.style.color = '#fb7185';

    failureBox.style.display = 'block';
    document.getElementById('failed-step-name').innerText = 'System Execution';
    document.getElementById('failed-step-reason').innerText = err.message || String(err);
  }
}

// --- Dry Run Simulation ---
async function triggerDryRun() {
  const plan = currentChatPlan || currentTeachPlan;
  if (!plan) return;

  const res = await safeFetchJson('/api/workflows/dry-run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan: plan, mode: activeMode })
  });

  if (res.preview) {
    renderDryRunModal(res.preview, () => {
      if (currentChatPlan) approveAndRunChatPlan();
      else if (currentTeachPlan) approveAndRunTeachPlan();
    });
  }
}

async function approveTeachPlan() {
  if (!currentTeachPlan) return;
  const defaultName = currentTeachPlan.title || currentTeachPlan.name || currentTeachPlan.goal || "Learned Workflow";
  const customTitle = prompt("Enter a title for your learned workflow:", defaultName);
  if (customTitle === null) return;
  const titleToSave = customTitle.trim() || defaultName;

  currentTeachPlan.title = titleToSave;
  currentTeachPlan.name = titleToSave;
  currentTeachPlan.goal = titleToSave;
  currentTeachPlan.is_saved = true;

  let wfId = currentTeachWorkflowId || (currentTeachPlan ? (currentTeachPlan.id || currentTeachPlan.workflow_id) : null);
  try {
    const res = await fetch('/api/workflows/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_id: wfId, title: titleToSave, name: titleToSave, goal: titleToSave, plan: currentTeachPlan, mode: activeMode })
    });
    const data = await res.json();
    if (!res.ok || !data.success || (!data.workflow_id && !data.id)) {
      console.error('[SAVE WORKFLOW ERROR]', data);
      alert(`Failed to save workflow: ${data.detail || data.error || data.message || 'Server error'}`);
      return;
    }

    const savedWfId = data.workflow_id || data.id;
    wfId = savedWfId;
    currentTeachWorkflowId = wfId;
    currentTeachPlan.id = wfId;
    currentTeachPlan.workflow_id = wfId;
    currentTeachPlan.is_saved = true;
    const idBadge = document.getElementById('teach-wf-id-badge');
    if (idBadge) idBadge.innerText = `ID: #${wfId} | REC: ${data.recording_id || 'R001'}`;

    alert(`Workflow "${titleToSave}" saved successfully! (ID: #${wfId})`);
    switchTab('workflows');
  } catch (err) {
    console.error('[SAVE WORKFLOW NETWORK ERROR]', err);
    alert(`Error saving workflow: ${err.message || String(err)}`);
  }
}

async function saveChatPlan() {
  if (!currentChatPlan) return;
  const defaultName = currentChatPlan.title || currentChatPlan.name || currentChatPlan.goal || "My Chat Workflow";
  const customTitle = prompt("Enter a title for your saved workflow:", defaultName);
  if (customTitle === null) return;
  const titleToSave = customTitle.trim() || defaultName;
  currentChatPlan.title = titleToSave;
  currentChatPlan.name = titleToSave;
  currentChatPlan.goal = titleToSave;
  currentChatPlan.is_saved = true;

  let wfId = currentChatPlan.id || currentChatPlan.workflow_id;
  try {
    const res = await fetch('/api/workflows/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow_id: wfId, title: titleToSave, name: titleToSave, goal: titleToSave, plan: currentChatPlan, mode: activeMode })
    });
    const data = await res.json();
    if (!res.ok || !data.success || (!data.workflow_id && !data.id)) {
      console.error('[SAVE CHAT WORKFLOW ERROR]', data);
      alert(`Failed to save workflow: ${data.detail || data.error || data.message || 'Server error'}`);
      return;
    }

    const savedWfId = data.workflow_id || data.id;
    currentChatPlan.id = savedWfId;
    currentChatPlan.workflow_id = savedWfId;

    alert(`Workflow "${titleToSave}" saved to My Workflows! (ID: #${savedWfId})`);
    switchTab('workflows');
  } catch (err) {
    console.error('[SAVE CHAT WORKFLOW NETWORK ERROR]', err);
    alert(`Error saving workflow: ${err.message || String(err)}`);
  }
}

function editTeachPlan() {
  if (currentTeachPlan) {
    switchTab('chat');
    document.getElementById('chat-input').value = currentTeachPlan.goal;
    document.getElementById('chat-input').focus();
  }
}

async function rejectTeachPlan() {
  const wfId = currentTeachWorkflowId || (currentTeachPlan ? (currentTeachPlan.id || currentTeachPlan.workflow_id) : null);
  if (wfId) {
    try {
      await fetch('/api/workflows/discard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: wfId })
      });
    } catch (e) {}
  }
  document.getElementById('teach-result-card').style.display = 'none';
  currentTeachPlan = null;
  currentTeachWorkflowId = null;
}

// --- Evolution Engine ---
async function acceptWorkflowEvolution() {
  if (!currentEvolution) return;
  const res = await fetch('/api/evolution/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workflow_id: currentEvolution.workflow_id,
      new_actions: currentEvolution.new_actions,
      change_reason: currentEvolution.change_summary
    })
  });
  const data = await res.json();
  alert(`Workflow evolved successfully! New Active Version: v${data.new_version}`);
  document.getElementById('evolution-proposal-box').style.display = 'none';
  switchTab('workflows');
}

function keepOldWorkflow() {
  alert("Old workflow version kept active.");
  document.getElementById('evolution-proposal-box').style.display = 'none';
}

function dismissEvolution() {
  document.getElementById('evolution-proposal-box').style.display = 'none';
}

// --- Workflows Grid & Approval Flow ---
async function loadWorkflows() {
  const res = await fetch('/api/workflows');
  const data = await res.json();
  const grid = document.getElementById('workflows-grid');

  if (!data.workflows || data.workflows.length === 0) {
    grid.innerHTML = '<div style="color: var(--text-muted); grid-column: 1/-1;">No workflows saved yet. Create one via Chat or Teach by Doing!</div>';
    return;
  }

  grid.innerHTML = data.workflows.map(wf => {
    const displayTitle = wf.title || wf.name || wf.goal || "Untitled Workflow";
    return `
    <div class="card">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
        <h3 style="font-size: 1.1rem; color: #ffffff;">${displayTitle}</h3>
        <span class="badge badge-ver">v${wf.version}</span>
      </div>
      <p style="color: var(--text-muted); font-size: 0.82rem; margin-bottom: 0.85rem; height: 38px; overflow: hidden; text-overflow: ellipsis;">
        ${wf.description || wf.goal || displayTitle}
      </p>

      <div style="display: flex; gap: 0.4rem; margin-bottom: 0.85rem;">
        <span class="badge badge-${(wf.risk || 'LOW').toLowerCase()}">${wf.risk || 'LOW'} RISK</span>
        <span class="badge badge-low">${Math.round((wf.confidence || 0.85) * 100)}% CONFIDENCE</span>
      </div>

      <div style="display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--text-muted); border-top: 1px solid var(--border-color); padding-top: 0.65rem; margin-bottom: 0.85rem;">
        <span>Executions: ${wf.executions_count}</span>
        <span>Success: ${wf.success_count}</span>
      </div>

      <div style="display: flex; gap: 0.5rem;">
        <button class="btn btn-primary btn-sm" onclick="runSavedWorkflow(${wf.id})">Run</button>
        <button class="btn btn-secondary btn-sm" onclick="editSavedWorkflow(${wf.id})">Edit</button>
        <button class="btn btn-secondary btn-sm" onclick="viewWorkflowHistory(${wf.id})">History</button>
        <button class="btn btn-secondary btn-sm" style="color: #ef4444;" onclick="deleteSingleWorkflow(${wf.id})">Delete</button>
      </div>
    </div>
  `;
  }).join('');
}

async function runSavedWorkflow(wfId) {
  currentActiveWorkflowId = wfId;
  const res = await fetch(`/api/workflows/${wfId}`);
  const data = await res.json();
  const wf = data.workflow;
  const displayTitle = wf ? (wf.title || wf.name || wf.goal) : 'Saved Workflow';

  switchTab('chat');
  const targetMode = activeMode.toUpperCase();
  await runStreamingWorkflowExecution({
    workflow_id: wfId,
    mode: targetMode,
    ui_mode: targetMode,
    requested_mode: targetMode,
    actions: wf ? wf.actions : null,
    source: "saved",
    confirmed_medium: true,
    confirmed_high: true
  }, displayTitle);
}

function promptWorkflowApproval(wfId) {
  runSavedWorkflow(wfId);
}

async function deleteSingleWorkflow(wfId) {
  if (!confirm('Are you sure you want to delete this workflow?')) return;
  const res = await fetch(`/api/workflows/${wfId}`, { method: 'DELETE' });
  if (res.ok) {
    loadWorkflows();
  }
}

async function deleteAllWorkflows() {
  if (!confirm('Are you sure you want to delete ALL saved workflows from dashboard?')) return;
  const res = await fetch('/api/workflows', { method: 'DELETE' });
  if (res.ok) {
    loadWorkflows();
  }
}

async function executeFromApprovalModal() {
  if (!pendingModalWorkflowId) return;
  runSavedWorkflow(pendingModalWorkflowId);
}

async function editSavedWorkflow(wfId) {
  const res = await fetch(`/api/workflows/${wfId}`);
  const data = await res.json();
  const wf = data.workflow;
  if (!wf) return;
  const currentTitle = wf.title || wf.name || wf.goal || "Untitled Workflow";
  const newTitle = prompt("Edit Workflow Title:", currentTitle);
  if (newTitle === null) return;
  const titleToSave = newTitle.trim() || currentTitle;

  const saveRes = await fetch('/api/workflows/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workflow_id: wfId, title: titleToSave, name: titleToSave, goal: titleToSave, plan: wf })
  });
  const saveData = await saveRes.json();
  if (saveData.success || saveData.workflow_id) {
    loadWorkflows();
  }
}

function disableWorkflow(wfId) {
  alert(`Workflow #${wfId} disabled.`);
}

async function viewWorkflowHistory(id) {
  const res = await fetch(`/api/workflows/${id}/versions`);
  const data = await res.json();
  const container = document.getElementById('versions-list-container');
  if (!container) {
    const listStr = (data.versions || []).map(v => `Version ${v.version}: ${(v.actions || []).map(a => a.label || a.type).join(' → ')}`).join('\n');
    alert(`Workflow #${id} History:\n` + (listStr || 'Version 1'));
    return;
  }

  container.innerHTML = (data.versions || []).map(v => `
    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 10px; padding: 0.85rem;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 700; color: #93c5fd;">Version ${v.version}</span>
        <span style="font-size: 0.75rem; color: var(--text-muted);">${(v.created_at || '').split('T')[0]}</span>
      </div>
      <p style="font-size: 0.8rem; color: var(--text-muted); margin: 0.35rem 0;">Reason: ${v.change_reason || 'Creation'}</p>
      <div style="font-size: 0.78rem; font-family: var(--font-mono); color: #cbd5e1; margin-bottom: 0.5rem;">
        ${(v.actions || []).map(a => a.label || a.type).join(' → ')}
      </div>
      <button class="btn btn-secondary btn-sm" onclick="restoreVersion(${id}, ${v.version})">Restore This Version</button>
    </div>
  `).join('');

  openModal('versions-modal');
}

async function restoreVersion(workflowId, targetVersion) {
  const res = await fetch('/api/workflows/restore-version', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workflow_id: workflowId, target_version: targetVersion })
  });
  const data = await res.json();
  alert(`Restored version ${targetVersion} as active version!`);
  closeModal('versions-modal');
  loadWorkflows();
}

// --- User Correction ---
function openCorrectionModal() {
  openModal('correction-modal');
}

async function submitCorrection(remember) {
  const feedback = document.getElementById('correction-feedback').value;
  const targetDest = document.getElementById('correction-dest').value;

  if (!currentActiveWorkflowId) {
    alert('Please run or select a workflow first.');
    closeModal('correction-modal');
    return;
  }

  const res = await fetch('/api/corrections', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workflow_id: currentActiveWorkflowId,
      execution_id: currentActiveExecutionId,
      feedback_text: feedback,
      original_action: { type: "MOVE_FILE", params: { destination: "Other" } },
      corrected_action: { type: "MOVE_FILE", label: `Move to ${targetDest}`, params: { destination: targetDest }, risk: "LOW" },
      remember: remember
    })
  });
  const data = await res.json();
  alert(data.message);
  closeModal('correction-modal');
  loadWorkflows();
}

function reportProblem() {
  alert("Feedback recorded. You can also click 'Correct Workflow' to teach WorkFlowOS the right behavior.");
}

// --- Activity & Settings ---
async function loadActivityLog() {
  const res = await fetch('/api/activity');
  const data = await res.json();
  const tbody = document.getElementById('activity-tbody');

  tbody.innerHTML = (data.activity || []).map(e => `
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
      <td style="padding: 0.65rem; color: var(--text-muted);">${(e.timestamp || '').replace('T', ' ').split('.')[0]}</td>
      <td style="padding: 0.65rem; font-weight: 600; color: #34d399;">${e.semantic_action}</td>
      <td style="padding: 0.65rem; font-family: var(--font-mono); font-size: 0.78rem;">${e.app_name || '-'}</td>
      <td style="padding: 0.65rem;">${e.window_title || '-'}</td>
      <td style="padding: 0.65rem; font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">${JSON.stringify(e.details)}</td>
    </tr>
  `).join('');
}

async function loadSettings() {
  const res = await fetch('/api/settings');
  const data = await res.json();
  const s = data.settings || {};
  if (s.gemini_api_key) document.getElementById('setting-gemini-key').value = s.gemini_api_key;
  if (s.default_mode) {
    document.getElementById('setting-default-mode').value = s.default_mode;
    setMode(s.default_mode);
  }
}

async function saveSettings() {
  const key = document.getElementById('setting-gemini-key').value.trim();
  const defMode = document.getElementById('setting-default-mode').value;
  await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      settings: {
        gemini_api_key: key,
        default_mode: defMode
      }
    })
  });
  alert('Preferences saved successfully!');
}

// --- Sandbox Explorer ---
async function showSandboxModal() {
  await loadSandboxStatus();
  openModal('sandbox-modal');
}

async function loadSandboxStatus() {
  const res = await fetch('/api/sandbox/status');
  const data = await res.json();
  const display = document.getElementById('sandbox-tree-display');

  let html = `<div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.65rem;">Sandbox: ${data.sandbox_path}</div>`;
  for (const [folder, files] of Object.entries(data.tree || {})) {
    html += `
      <div style="margin-bottom: 0.75rem;">
        <div style="font-weight: 700; color: #93c5fd; font-size: 0.85rem;">📁 ${folder}/</div>
        <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.4rem;">
          ${files.length ? files.map(f => `<span style="background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border-color); padding: 0.35rem 0.7rem; border-radius: 6px; font-family: var(--font-mono); font-size: 0.76rem;">📄 ${f}</span>`).join('') : '<span style="color: var(--text-muted); font-size: 0.75rem;">(empty folder)</span>'}
        </div>
      </div>
    `;
  }
  display.innerHTML = html;
}

async function resetSandboxFiles() {
  await fetch('/api/sandbox/reset', { method: 'POST' });
  alert('Sandbox reset with fresh demo placement documents!');
  loadSandboxStatus();
}

// --- Modal Helpers ---
function openModal(id) { 
  const el = document.getElementById(id);
  if (el) el.classList.add('open'); 
}
function closeModal(id) { 
  const el = document.getElementById(id);
  if (el) el.classList.remove('open'); 
}

function renderDryRunModal(preview, confirmCallback) {
  const list = document.getElementById('dry-run-steps-list');
  if (list) {
    list.innerHTML = (preview.steps || []).map(s => `
      <div class="step-item">
        <div class="step-num">${s.step}</div>
        <div style="flex: 1;">
          <div style="font-weight: 600;">${s.label}</div>
          <div style="color: #34d399; font-size: 0.78rem;">${s.preview_message}</div>
        </div>
        <span class="badge badge-${(s.risk || 'LOW').toLowerCase()}">${s.risk || 'LOW'}</span>
      </div>
    `).join('');
  }

  const confirmBtn = document.getElementById('dry-run-confirm-btn');
  if (confirmBtn) {
    confirmBtn.onclick = () => {
      closeModal('dry-run-modal');
      confirmCallback();
    };
  }
  openModal('dry-run-modal');
}

// Initial Load
window.onload = () => {
  loadWorkflows();
  updateRecordingBadge(false);
};
