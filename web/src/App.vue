<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'

type ObservationSource = {
  type: 'RADAR' | 'EO_IR' | 'PRIOR_KNOWLEDGE'
  noiseStdDev: number
  missingRate: number
  delaySteps: number
  confidence: number
}

type ExperimentConfig = {
  scenarioName: string
  targetCount: number
  simulationSteps: number
  timeStepSeconds: number
  availableResources: number
  fusionMethod: string
  schedulingPolicy: 'ROUND_ROBIN' | 'PRIORITY'
  randomSeed: number
  observationSources: ObservationSource[]
}

type TargetState = {
  targetId: number
  x: number
  y: number
  velocityX: number
  velocityY: number
  timeStep: number
}

type FusedState = TargetState & {
  uncertainty: number
  associationConfidence: number
  predictedOnly: boolean
}

type StepResult = {
  timeStep: number
  trueStates: TargetState[]
  observations: Array<{
    targetId: number
    sourceType: string
    x: number
    y: number
    confidence: number
    available: boolean
  }>
  fusedStates: FusedState[]
  scheduling: {
    policy: string
    allocatedTargetIds: number[]
    assignments: Array<{
      targetId: number
      allocated: boolean
      priorityScore: number
      reason: string
    }>
  }
  metrics: {
    averagePositionError: number
    trackingRate: number
    resourceUtilization: number
    allocatedTargetCount: number
    unservedTargetCount: number
  }
}

type SimulationResult = {
  runId: string
  config: ExperimentConfig
  steps: StepResult[]
  metrics: {
    averagePositionError: number
    trackingRate: number
    resourceUtilization: number
    averageWaitingTime: number
    schedulingSwitches: number
    totalSteps: number
  }
}

type SimulationRunDetail = {
  runId: string
  truth: TargetState[]
  observations: Array<{
    timeStep: number
    targetId: number
    sourceType: string
    available: boolean
    x: number
    y: number
    confidence: number
  }>
  fusedStates: FusedState[]
  assignments: Array<{
    timeStep: number
    targetId: number
    allocated: boolean
    priorityRank: number
    priorityScore: number
    reason: string
  }>
  metrics: Array<{
    timeStep: number
    averagePositionError: number
    trackingRate: number
    resourceUtilization: number
    allocatedTargetCount: number
    unservedTargetCount: number
  }>
}
type ComparisonResult = {
  roundRobin: SimulationResult
  priority: SimulationResult
  priorityMinusRoundRobin: {
    averagePositionErrorDelta: number
    trackingRateDelta: number
    resourceUtilizationDelta: number
    averageWaitingTimeDelta: number
    schedulingSwitchesDelta: number
  }
}


type AgentPlan = {
  title: string
  goal: string
  assumptions: string[]
  experiment_config: Record<string, unknown>
  baselines: string[]
  metrics: string[]
  execution_steps: string[]
  expected_outputs: string[]
  requires_confirmation: boolean
  planner?: string
  model?: string | null
}

type AgentTrace = {
  trace_id: string
  request: { goal: string }
  plan: AgentPlan
  confirmed: boolean
  status: string
  events: Array<{ event_id: string; event_type: string; created_at: string }>
  last_result: Record<string, unknown> | null
  analysis: {
    summary: string
    metrics: Record<string, unknown>
    evidence: Array<{ metric: string; value: unknown; source: string }>
    limitations: string[]
  } | null
}

type AgentToolResult = {
  trace_id: string
  tool_name: string
  result: Record<string, unknown>
  analysis: AgentTrace['analysis']
}
type AuthUser = {
  userId: number
  username: string
  email: string
  displayName: string
  role: string
  status: string
}
type LoginResponse = {
  accessToken: string
  expiresAt: string
  user: AuthUser
}
type CaptchaChallenge = {
  challengeId: string
  question: string
  expiresAt: string
}
type PasswordResetResponse = {
  message: string
  developmentResetToken: string | null
}
type AgentView = 'workbench' | 'agent'
type AgentModelStatus = {
  current: {
    provider: string
    label: string
    protocol: string
    model: string | null
    configured: boolean
    fallbackToRule: boolean
  }
  providers: Array<{
    provider: string
    label: string
    protocol: string
    defaultModel: string
    modelOptions: string[]
    configured: boolean
  }>
}

const config = ref<ExperimentConfig>({
  scenarioName: 'multi-target-demo',
  targetCount: 3,
  simulationSteps: 40,
  timeStepSeconds: 1,
  availableResources: 2,
  fusionMethod: 'WEIGHTED_AVERAGE',
  schedulingPolicy: 'ROUND_ROBIN',
  randomSeed: 20260928,
  observationSources: [
    { type: 'RADAR', noiseStdDev: 3, missingRate: 0.05, delaySteps: 0, confidence: 0.9 },
    { type: 'EO_IR', noiseStdDev: 5, missingRate: 0.15, delaySteps: 1, confidence: 0.75 },
    { type: 'PRIOR_KNOWLEDGE', noiseStdDev: 8, missingRate: 0.25, delaySteps: 0, confidence: 0.55 }
  ]
})

const simulation = ref<SimulationResult | null>(null)
const comparison = ref<ComparisonResult | null>(null)
const sceneLoaded = ref(false)
const loading = ref(false)
const loadingConfig = ref(false)
const errorMessage = ref('')
const progressPercent = ref(0)
const progressText = ref('')
const activeStep = ref(0)
const chartElement = ref<HTMLDivElement | null>(null)
const activeController = ref<AbortController | null>(null)
const activeRunToken = ref(0)
const authUser = ref<AuthUser | null>(null)
const authToken = ref('')
const authMode = ref<'login' | 'register' | 'forgot' | 'reset'>('login')
const authModalOpen = ref(false)
const authBusy = ref(false)
const authError = ref('')
const authMessage = ref('')
const captcha = ref<CaptchaChallenge | null>(null)
const captchaAnswer = ref('')
const showPassword = ref(false)
const showNewPassword = ref(false)
const authForm = ref({ login: '', username: '', email: '', password: '', displayName: '', resetToken: '', newPassword: '' })
const activeView = ref<AgentView>(window.location.pathname === '/agent' ? 'agent' : 'workbench')
const agentModelStatus = ref<AgentModelStatus | null>(null)
const selectedAgentProvider = ref('rule')
const selectedAgentModel = ref('')
let chart: echarts.ECharts | null = null
let progressTimer: number | undefined
const REQUEST_TIMEOUT_MS = 30_000
const RUN_WATCHDOG_MS = 32_000
const PASSWORD_PATTERN = /^(?=.{10,100}$)(?:(?=.*[A-Za-z])(?=.*\d)|(?=.*[A-Za-z])(?=.*[^A-Za-z\d])|(?=.*\d)(?=.*[^A-Za-z\d])).*$/

const activeMetrics = computed(() => simulation.value?.metrics ?? null)
const currentStep = computed(() => simulation.value?.steps[activeStep.value] ?? null)
const visibleSteps = computed(() => simulation.value?.steps.slice(-12).reverse() ?? [])
const canRun = computed(() => !loading.value && !loadingConfig.value)
const selectedProviderInfo = computed(() => {
  if (selectedAgentProvider.value === 'rule') return null
  return agentModelStatus.value?.providers.find((item) => item.provider === selectedAgentProvider.value) ?? null
})
const selectedProviderLabel = computed(() => selectedProviderInfo.value?.label ?? 'Rule-based Agent')
const selectedModelOptions = computed(() => {
  if (selectedAgentProvider.value === 'rule') return ['Local deterministic planner']
  const options = selectedProviderInfo.value?.modelOptions ?? []
  const fallback = selectedProviderInfo.value?.defaultModel
  return options.length ? options : fallback ? [fallback] : []
})
const selectedModelName = computed(() => {
  if (selectedAgentProvider.value === 'rule') return 'Local deterministic planner'
  return selectedAgentModel.value || selectedProviderInfo.value?.defaultModel || ''
})

function formatNumber(value: number | undefined, digits = 2) {
  return value === undefined ? '--' : value.toFixed(digits)
}

function passwordMeetsRules(password: string) {
  const categoryCount = [/[A-Za-z]/.test(password), /\d/.test(password), /[^A-Za-z\d]/.test(password)]
    .filter(Boolean).length
  return password.length >= 10 && categoryCount >= 2
}

function passwordHint(password: string) {
  if (!password) return '至少 10 位，数字、字母、符号至少满足两类'
  return passwordMeetsRules(password)
    ? '密码强度符合要求'
    : '还需满足：至少 10 位，数字、字母、符号至少满足两类'
}

function sourceLabel(type: string) {
  return type === 'EO_IR' ? '\u5149\u7535/\u7ea2\u5916' : type === 'PRIOR_KNOWLEDGE' ? '\u5148\u9a8c' : '\u96f7\u8fbe'
}

function beginProgress(text: string) {
  clearProgress()
  progressPercent.value = 8
  progressText.value = text
  const tick = () => {
    if (!loading.value) return
    if (progressPercent.value < 90) {
      progressPercent.value = Math.min(
        90,
        progressPercent.value + (progressPercent.value < 45 ? 5 : 2)
      )
    }
    if (progressPercent.value >= 90) {
      progressText.value = '\u540e\u7aef\u4ecd\u5728\u8ba1\u7b97\uff0c\u8bf7\u7a0d\u5019...'
    }
    progressTimer = window.setTimeout(tick, 350)
  }
  progressTimer = window.setTimeout(tick, 350)
}

function finishProgress(text: string) {
  clearProgress()
  progressPercent.value = 100
  progressText.value = text
}

function clearProgress() {
  if (progressTimer !== undefined) {
    window.clearTimeout(progressTimer)
    progressTimer = undefined
  }
}

function cancelRun() {
  activeRunToken.value += 1
  activeController.value?.abort()
  activeController.value = null
  loading.value = false
  clearProgress()
  progressPercent.value = 0
  progressText.value = '\u5df2\u505c\u6b62\u7b49\u5f85'
  errorMessage.value = '\u5df2\u53d6\u6d88\u672c\u6b21\u64cd\u4f5c\u3002'
}

async function request<T>(
  url: string,
  options?: RequestInit,
  controller = new AbortController()
): Promise<T> {
  let timedOut = false
  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...(authToken.value ? { Authorization: `Bearer ${authToken.value}` } : {})
      },
      ...options,
      signal: controller.signal
    })
    const payload = await response.json()
    if (!response.ok || payload.success === false) {
      throw new Error(payload.message || 'Backend request failed')
    }
    return payload.data as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (timedOut) {
        throw new Error(`Request timed out: ${url}`)
      }
      throw error
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}

async function submitAuth() {
  authBusy.value = true
  authError.value = ''
  authMessage.value = ''
  try {
    if (authMode.value === 'register') {
      if (!passwordMeetsRules(authForm.value.password)) {
        throw new Error('密码至少 10 位，且数字、字母、符号至少满足两类。')
      }
      await request<AuthUser>('/api/v1/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          username: authForm.value.username,
          email: authForm.value.email,
          password: authForm.value.password,
          displayName: authForm.value.displayName,
          captchaId: captcha.value?.challengeId,
          captchaAnswer: captchaAnswer.value
        })
      })
      authMode.value = 'login'
      authForm.value.login = authForm.value.username
      authForm.value.password = ''
      authMessage.value = '注册成功，请使用新账号登录。'
    } else {
      const result = await request<LoginResponse>('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          login: authForm.value.login,
          password: authForm.value.password,
          captchaId: captcha.value?.challengeId,
          captchaAnswer: captchaAnswer.value
        })
      })
      authToken.value = result.accessToken
      authUser.value = result.user
      authModalOpen.value = false
      localStorage.setItem('fusionpilot_access_token', result.accessToken)
      localStorage.setItem('fusionpilot_user', JSON.stringify(result.user))
      void loadAgentModelStatus()
      void loadDefaultConfig()
      authForm.value.password = ''
      authMessage.value = '登录成功。'
    }
  } catch (error) {
    authError.value = error instanceof Error ? error.message : String(error)
  } finally {
    authBusy.value = false
  }
}

async function loadCaptcha() {
  try {
    captcha.value = await request<CaptchaChallenge>('/api/v1/auth/captcha')
    captchaAnswer.value = ''
  } catch (error) {
    authError.value = error instanceof Error ? error.message : String(error)
  }
}

async function openAuth(mode: 'login' | 'register' | 'forgot') {
  authMode.value = mode
  authModalOpen.value = true
  authError.value = ''
  authMessage.value = ''
  await loadCaptcha()
}

async function submitForgot() {
  authBusy.value = true
  authError.value = ''
  authMessage.value = ''
  try {
    const result = await request<PasswordResetResponse>('/api/v1/auth/password-reset/request', {
      method: 'POST',
      body: JSON.stringify({
        login: authForm.value.login,
        captchaId: captcha.value?.challengeId,
        captchaAnswer: captchaAnswer.value
      })
    })
    authMessage.value = result.developmentResetToken
      ? `${result.message} Token: ${result.developmentResetToken}`
      : result.message
    if (result.developmentResetToken) {
      authForm.value.resetToken = result.developmentResetToken
      authMode.value = 'reset'
    }
    await loadCaptcha()
  } catch (error) {
    authError.value = error instanceof Error ? error.message : String(error)
  } finally {
    authBusy.value = false
  }
}

async function submitReset() {
  authBusy.value = true
  authError.value = ''
  try {
    if (!passwordMeetsRules(authForm.value.newPassword)) {
      throw new Error('密码至少 10 位，且数字、字母、符号至少满足两类。')
    }
    await request('/api/v1/auth/password-reset/confirm', {
      method: 'POST',
      body: JSON.stringify({
        resetToken: authForm.value.resetToken,
        newPassword: authForm.value.newPassword
      })
    })
    authMode.value = 'login'
    authForm.value.password = ''
    authForm.value.newPassword = ''
    authMessage.value = '密码已重置，请使用新密码登录。'
    await loadCaptcha()
  } catch (error) {
    authError.value = error instanceof Error ? error.message : String(error)
  } finally {
    authBusy.value = false
  }
}

async function logout() {
  try {
    if (authToken.value) {
      await request('/api/v1/auth/logout', { method: 'POST' })
    }
  } catch {
    // Clear local state even if the server is unavailable.
  }
  authToken.value = ''
  authUser.value = null
  localStorage.removeItem('fusionpilot_access_token')
  localStorage.removeItem('fusionpilot_user')
  activeView.value = 'workbench'
  window.history.pushState({}, '', '/')
  authMessage.value = '已退出登录。'
}

function buildStepResults(base: SimulationResult, detail: SimulationRunDetail): StepResult[] {
  const timeSteps = Array.from(new Set([
    ...detail.truth.map((item) => item.timeStep),
    ...detail.observations.map((item) => item.timeStep),
    ...detail.fusedStates.map((item) => item.timeStep),
    ...detail.assignments.map((item) => item.timeStep),
    ...detail.metrics.map((item) => item.timeStep)
  ])).sort((left, right) => left - right)

  return timeSteps.map((timeStep) => {
    const assignments = detail.assignments
      .filter((item) => item.timeStep === timeStep)
      .map((item) => ({
        targetId: item.targetId,
        allocated: item.allocated,
        priorityScore: item.priorityScore,
        reason: item.reason
      }))
    const metrics = detail.metrics.find((item) => item.timeStep === timeStep) ?? {
      timeStep,
      averagePositionError: 0,
      trackingRate: 0,
      resourceUtilization: 0,
      allocatedTargetCount: 0,
      unservedTargetCount: base.config.targetCount
    }

    return {
      timeStep,
      trueStates: detail.truth.filter((item) => item.timeStep === timeStep),
      observations: detail.observations.filter((item) => item.timeStep === timeStep),
      fusedStates: detail.fusedStates.filter((item) => item.timeStep === timeStep),
      scheduling: {
        policy: base.config.schedulingPolicy,
        allocatedTargetIds: assignments.filter((item) => item.allocated).map((item) => item.targetId),
        assignments
      },
      metrics
    }
  })
}

async function loadSimulationDetail(result: SimulationResult): Promise<SimulationResult> {
  const detail = await request<SimulationRunDetail>(`/api/v1/simulations/${result.runId}/detail`)
  const steps = buildStepResults(result, detail)
  return { ...result, steps }
}

async function refreshSimulationDetailInBackground(result: SimulationResult, token: number) {
  try {
    const detailed = await loadSimulationDetail(result)
    if (activeRunToken.value !== token || simulation.value?.runId !== result.runId) return
    simulation.value = detailed
    activeStep.value = 0
    await nextTick()
    renderChart()
    progressText.value = '\u5df2\u540c\u6b65\u6570\u636e\u5e93\u56de\u653e\u660e\u7ec6'
  } catch (error) {
    if (activeRunToken.value !== token) return
    progressText.value = '\u4eff\u771f\u5df2\u5b8c\u6210\uff0c\u660e\u7ec6\u56de\u653e\u63a5\u53e3\u6682\u672a\u8fd4\u56de'
  }
}
async function loadDefaultConfig(): Promise<boolean> {
  loadingConfig.value = true
  errorMessage.value = ''
  try {
    config.value = await request<ExperimentConfig>('/api/v1/experiments/default')
    config.value.simulationSteps = Math.min(config.value.simulationSteps, 60)
    sceneLoaded.value = true
    simulation.value = null
    comparison.value = null
    activeStep.value = 0
    chart?.dispose()
    chart = null
    return true
  } catch (error) {
    errorMessage.value = '&#26080;&#27861;&#36830;&#25509; Java &#21518;&#31471;&#65306;' + String(error)
    return false
  } finally {
    loadingConfig.value = false
  }
}

async function ensureSceneLoaded(): Promise<boolean> {
  if (sceneLoaded.value) return true
  return loadDefaultConfig()
}

async function runSimulation() {
  if (!(await ensureSceneLoaded())) {
    errorMessage.value = '\u65e0\u6cd5\u81ea\u52a8\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f\uff0c\u8bf7\u68c0\u67e5 Java \u540e\u7aef\u3002'
    return
  }
  const token = activeRunToken.value + 1
  activeRunToken.value = token
  loading.value = true
  errorMessage.value = ''
  comparison.value = null
  beginProgress('\u5df2\u63d0\u4ea4\u4eff\u771f\u8bf7\u6c42')
  const controller = new AbortController()
  activeController.value = controller
  const watchdogId = window.setTimeout(() => {
    if (activeRunToken.value !== token || !loading.value) return
    activeRunToken.value += 1
    controller.abort()
    if (activeController.value === controller) {
      activeController.value = null
    }
    loading.value = false
    clearProgress()
    progressPercent.value = 0
    progressText.value = '\u4eff\u771f\u8bf7\u6c42\u8d85\u65f6'
    errorMessage.value = '\u524d\u7aef\u7b49\u5f85 Java \u4eff\u771f\u8d85\u8fc7 30 \u79d2\u3002\u8bf7\u68c0\u67e5 Java \u540e\u7aef\u7ec8\u7aef\u65e5\u5fd7\u3002'
  }, RUN_WATCHDOG_MS)
  let result: SimulationResult
  try {
    result = await request<SimulationResult>('/api/v1/simulations/run', {
      method: 'POST',
      body: JSON.stringify(config.value)
    }, controller)
  } catch (error) {
    if (activeRunToken.value === token && !(error instanceof DOMException && error.name === 'AbortError')) {
      errorMessage.value = '\u4eff\u771f\u8fd0\u884c\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
      clearProgress()
      progressPercent.value = 0
      progressText.value = '\u4eff\u771f\u5931\u8d25'
    }
    return
  } finally {
    window.clearTimeout(watchdogId)
    if (activeController.value === controller) {
      activeController.value = null
    }
    if (activeRunToken.value === token) {
      loading.value = false
    }
  }
  if (activeRunToken.value !== token) return
  progressPercent.value = 96
  progressText.value = '\u5df2\u6536\u5230\u4eff\u771f\u7ed3\u679c\uff0c\u6b63\u5728\u66f4\u65b0\u754c\u9762...'
  simulation.value = result
  activeStep.value = 0
  await nextTick()
  try {
    renderChart()
    finishProgress('\u4eff\u771f\u5df2\u5b8c\u6210')
    void refreshSimulationDetailInBackground(result, token)
  } catch (error) {
    errorMessage.value = '\u4eff\u771f\u5df2\u5b8c\u6210\uff0c\u4f46\u8f68\u8ff9\u56fe\u6e32\u67d3\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
    clearProgress()
  }
}

async function comparePolicies() {
  if (!(await ensureSceneLoaded())) {
    errorMessage.value = '\u65e0\u6cd5\u81ea\u52a8\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f\uff0c\u8bf7\u68c0\u67e5 Java \u540e\u7aef\u3002'
    return
  }
  const token = activeRunToken.value + 1
  activeRunToken.value = token
  loading.value = true
  errorMessage.value = ''
  beginProgress('\u6b63\u5728\u8fd0\u884c\u4e24\u79cd\u8c03\u5ea6\u7b56\u7565')
  const controller = new AbortController()
  activeController.value = controller
  const watchdogId = window.setTimeout(() => {
    if (activeRunToken.value !== token || !loading.value) return
    activeRunToken.value += 1
    controller.abort()
    if (activeController.value === controller) {
      activeController.value = null
    }
    loading.value = false
    clearProgress()
    progressPercent.value = 0
    progressText.value = '\u7b56\u7565\u5bf9\u6bd4\u8bf7\u6c42\u8d85\u65f6'
    errorMessage.value = '\u524d\u7aef\u7b49\u5f85 Java \u7b56\u7565\u5bf9\u6bd4\u8d85\u8fc7 30 \u79d2\u3002\u8bf7\u68c0\u67e5 Java \u540e\u7aef\u7ec8\u7aef\u65e5\u5fd7\u3002'
  }, RUN_WATCHDOG_MS)
  let result: ComparisonResult
  try {
    result = await request<ComparisonResult>('/api/v1/simulations/compare', {
      method: 'POST',
      body: JSON.stringify(config.value)
    }, controller)
  } catch (error) {
    if (activeRunToken.value === token && !(error instanceof DOMException && error.name === 'AbortError')) {
      errorMessage.value = '\u7b56\u7565\u5bf9\u6bd4\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
      clearProgress()
      progressPercent.value = 0
      progressText.value = '\u7b56\u7565\u5bf9\u6bd4\u5931\u8d25'
    }
    return
  } finally {
    window.clearTimeout(watchdogId)
    if (activeController.value === controller) {
      activeController.value = null
    }
    if (activeRunToken.value === token) {
      loading.value = false
    }
  }
  if (activeRunToken.value !== token) return
  progressPercent.value = 96
  progressText.value = '\u5bf9\u6bd4\u7ed3\u679c\u5df2\u8fd4\u56de\uff0c\u6b63\u5728\u66f4\u65b0\u754c\u9762...'
  comparison.value = result
  simulation.value = result.priority
  activeStep.value = 0
  await nextTick()
  try {
    renderChart()
    finishProgress('\u7b56\u7565\u5bf9\u6bd4\u5b8c\u6210')
    void refreshSimulationDetailInBackground(result.priority, token)
  } catch (error) {
    errorMessage.value = '\u5bf9\u6bd4\u5df2\u5b8c\u6210\uff0c\u4f46\u8f68\u8ff9\u56fe\u6e32\u67d3\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
    clearProgress()
  }
}


const agentGoal = ref('\u6bd4\u8f83\u8f6e\u8be2\u8c03\u5ea6\u4e0e\u4f18\u5148\u7ea7\u8c03\u5ea6\u5728\u591a\u76ee\u6807\u9ad8\u566a\u58f0\u573a\u666f\u4e0b\u7684\u8ddf\u8e2a\u8868\u73b0')
const agentSession = ref<AgentTrace | null>(null)
const agentResult = ref<AgentToolResult | null>(null)
const agentBusy = ref(false)
const agentMessage = ref('')
const agentError = ref('')
const agentTool = ref<'validate_experiment' | 'run_simulation' | 'calculate_metrics' | 'compare_scheduling_policies'>('run_simulation')

async function requestAgent<T>(url: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...(authToken.value ? { Authorization: `Bearer ${authToken.value}` } : {})
      },
      ...options,
      signal: controller.signal
    })
    const payload = await response.json()
    if (!response.ok) {
      const detail = payload.detail
      throw new Error(typeof detail === 'object' ? detail.message : String(detail || 'Agent request failed'))
    }
    return payload as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Agent request timed out after 15 seconds.')
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}

function navigateTo(view: AgentView) {
  activeView.value = view
  const path = view === 'agent' ? '/agent' : '/'
  window.history.pushState({}, '', path)
  window.scrollTo({ top: 0, behavior: 'smooth' })
  if (authUser.value) {
    if (view === 'workbench') void ensureSceneLoaded()
    if (view === 'agent') void loadAgentModelStatus()
  }
}

function handlePopState() {
  activeView.value = window.location.pathname === '/agent' ? 'agent' : 'workbench'
}

function handleAgentProviderChange() {
  if (selectedAgentProvider.value === 'rule') {
    selectedAgentModel.value = ''
    return
  }
  selectedAgentModel.value = selectedProviderInfo.value?.defaultModel ?? selectedModelOptions.value[0] ?? ''
}

async function loadAgentModelStatus() {
  try {
    agentModelStatus.value = await requestAgent<AgentModelStatus>('/api/v1/agent/models')
    selectedAgentProvider.value = agentModelStatus.value.current.provider
    if (selectedAgentProvider.value === 'rule') {
      selectedAgentModel.value = ''
    } else {
      selectedAgentModel.value = agentModelStatus.value.current.model ?? selectedProviderInfo.value?.defaultModel ?? ''
    }
  } catch {
    agentModelStatus.value = null
  }
}

function resetAgentMessages() {
  agentMessage.value = ''
  agentError.value = ''
}

async function createAgentSession() {
  resetAgentMessages()
  agentBusy.value = true
  try {
    if (!(await ensureSceneLoaded())) {
      throw new Error('\u65e0\u6cd5\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f')
    }
    agentSession.value = await requestAgent<AgentTrace>('/api/v1/agent/sessions', {
      method: 'POST',
      body: JSON.stringify({
        goal: agentGoal.value,
        target_count: config.value.targetCount,
        simulation_steps: config.value.simulationSteps,
        scheduling_policy: config.value.schedulingPolicy,
        compare_policies: agentGoal.value.includes('\u6bd4\u8f83') || agentGoal.value.toLowerCase().includes('compare'),
        model_provider: selectedAgentProvider.value,
        model_name: selectedAgentProvider.value === 'rule' ? null : selectedAgentModel.value.trim() || null
      })
    })
    agentResult.value = null
    agentMessage.value = '\u5b9e\u9a8c\u8ba1\u5212\u5df2\u751f\u6210\uff0c\u8bf7\u5ba1\u9605\u540e\u786e\u8ba4\u3002'
  } catch (error) {
    agentError.value = '\u65e0\u6cd5\u521b\u5efa Agent \u4f1a\u8bdd\uff1a' + String(error)
  } finally {
    agentBusy.value = false
  }
}

async function confirmAgentSession() {
  if (!agentSession.value) return
  resetAgentMessages()
  agentBusy.value = true
  try {
    await requestAgent(`/api/v1/agent/sessions/${agentSession.value.trace_id}/confirm`, { method: 'POST' })
    agentSession.value.confirmed = true
    agentSession.value.status = 'CONFIRMED'
    agentMessage.value = '\u8ba1\u5212\u5df2\u786e\u8ba4\uff0c\u73b0\u5728\u53ef\u4ee5\u9009\u62e9\u5de5\u5177\u6267\u884c\u3002'
  } catch (error) {
    agentError.value = '\u786e\u8ba4\u8ba1\u5212\u5931\u8d25\uff1a' + String(error)
  } finally {
    agentBusy.value = false
  }
}

function isSimulationResult(value: Record<string, unknown>): value is SimulationResult {
  return Array.isArray(value.steps) && typeof value.runId === 'string' && typeof value.metrics === 'object'
}

async function executeAgentTool() {
  if (!agentSession.value?.confirmed) return
  resetAgentMessages()
  agentBusy.value = true
  agentMessage.value = '\u6b63\u5728\u8c03\u7528 Agent \u5de5\u5177\uff0c\u8bf7\u7a0d\u5019...'
  const traceId = agentSession.value.trace_id
  const selectedTool = agentTool.value

  try {
    let result: AgentToolResult
    try {
      result = await Promise.race([
        requestAgent<AgentToolResult>(
          `/api/v1/agent/sessions/${traceId}/execute`,
          {
            method: 'POST',
            body: JSON.stringify({ tool_name: selectedTool })
          }
        ),
        new Promise<AgentToolResult>((_, reject) => {
          window.setTimeout(() => reject(new Error('Agent tool timeout')), 8000)
        })
      ])
    } catch (error) {
      if (selectedTool !== 'run_simulation') throw error
      const directResult = await request<SimulationResult>('/api/v1/simulations/run', {
        method: 'POST',
        body: JSON.stringify(agentSession.value.plan.experiment_config)
      })
      result = {
        trace_id: traceId,
        tool_name: selectedTool,
        result: directResult as unknown as Record<string, unknown>,
        analysis: {
          summary: '\u0041\u0067\u0065\u006e\u0074\u5de5\u5177\u8d85\u65f6\uff0c\u5df2\u4f7f\u7528 Java \u4eff\u771f\u5145\u5e95\uff1b\u4ee5\u4e0b\u7ed3\u679c\u4ecd\u6765\u81ea\u7ed3\u6784\u5316\u4eff\u771f\u6570\u636e\u3002',
          metrics: directResult.metrics as unknown as Record<string, unknown>,
          evidence: Object.entries(directResult.metrics).map(([metric, value]) => ({
            metric,
            value,
            source: 'java-backend-result'
          })),
          limitations: ['Agent execute request timed out; direct Java fallback was used.']
        }
      }
    }

    if (!result || !result.result) {
      throw new Error('\u5de5\u5177\u8fd4\u56de\u4e86\u7a7a\u7ed3\u679c')
    }
    agentResult.value = result
    agentSession.value.status = 'COMPLETED'
    agentSession.value.last_result = result.result
    agentSession.value.analysis = result.analysis
    agentBusy.value = false
    agentMessage.value = '\u5de5\u5177\u6267\u884c\u5b8c\u6210\uff0c\u7ed3\u679c\u5df2\u5199\u5165 Agent \u8f68\u8ff9\u3002'

    if (selectedTool === 'run_simulation') {
      if (!isSimulationResult(result.result)) {
        throw new Error('\u8fd4\u56de\u4e2d\u6ca1\u6709\u53ef\u7528\u7684\u8f68\u8ff9\u6570\u636e')
      }
      const token = activeRunToken.value + 1
      activeRunToken.value = token
      simulation.value = result.result
      sceneLoaded.value = true
      activeStep.value = 0
      await nextTick()
      try {
        renderChart()
        finishProgress('\u4eff\u771f\u5df2\u5b8c\u6210')
        void refreshSimulationDetailInBackground(simulation.value, token)
      } catch (renderError) {
        agentError.value = '\u8f68\u8ff9\u6570\u636e\u5df2\u8fd4\u56de\uff0c\u4f46\u56fe\u8868\u6e32\u67d3\u5931\u8d25\uff1a' + String(renderError)
      }
    }
  } catch (error) {
    agentMessage.value = ''
    agentError.value = '\u5de5\u5177\u6267\u884c\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
  } finally {
    agentBusy.value = false
  }
}

async function refreshAgentTrace() {
  if (!agentSession.value) return
  try {
    agentSession.value = await requestAgent<AgentTrace>(
      `/api/v1/agent/sessions/${agentSession.value.trace_id}`
    )
  } catch (error) {
    agentError.value = '\u65e0\u6cd5\u8bfb\u53d6 Agent \u8f68\u8ff9\uff1a' + String(error)
  }
}
function renderChart() {
  if (!chartElement.value || !simulation.value) return
  chart?.dispose()
  chart = echarts.init(chartElement.value)
  const colors = ['#38bdf8', '#a78bfa', '#fbbf24']
  const series = []
  for (const targetId of Array.from({ length: config.value.targetCount }, (_, index) => index + 1)) {
    const truth = simulation.value.steps.map((step) => {
      const state = step.trueStates.find((item) => item.targetId === targetId)
      return state ? [state.x, state.y] : [0, 0]
    })
    const fused = simulation.value.steps.map((step) => {
      const state = step.fusedStates.find((item) => item.targetId === targetId)
      return state ? [state.x, state.y] : [0, 0]
    })
    const color = colors[targetId - 1] ?? '#38bdf8'
    series.push(
      { name: `T${targetId} &#30495;&#23454;`, type: 'line', data: truth, symbol: 'none', lineStyle: { width: 2, color } },
      { name: `T${targetId} &#34701;&#21512;`, type: 'line', data: fused, symbol: 'circle', symbolSize: 5, lineStyle: { type: 'dashed', color } }
    )
  }
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { top: 4, textStyle: { color: '#9fb1c8' } },
    grid: { left: 42, right: 18, top: 42, bottom: 34 },
    xAxis: { type: 'value', name: 'X', axisLabel: { color: '#71839b' }, splitLine: { lineStyle: { color: '#203047' } } },
    yAxis: { type: 'value', name: 'Y', axisLabel: { color: '#71839b' }, splitLine: { lineStyle: { color: '#203047' } } },
    series
  })
}

function resizeChart() {
  chart?.resize()
}

onMounted(async () => {
  window.addEventListener('popstate', handlePopState)
  window.addEventListener('resize', resizeChart)
  const storedToken = localStorage.getItem('fusionpilot_access_token')
  if (storedToken) {
    try {
      authToken.value = storedToken
      authUser.value = await request<AuthUser>('/api/v1/auth/me')
      localStorage.setItem('fusionpilot_user', JSON.stringify(authUser.value))
      void loadAgentModelStatus()
      void loadDefaultConfig()
    } catch {
      authToken.value = ''
      authUser.value = null
      localStorage.removeItem('fusionpilot_access_token')
      localStorage.removeItem('fusionpilot_user')
      authMessage.value = '\u767b\u5f55\u5df2\u8fc7\u671f\uff0c\u8bf7\u91cd\u65b0\u767b\u5f55\u3002'
      authModalOpen.value = true
      void loadCaptcha()
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('popstate', handlePopState)
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup">
        <div class="brand-mark">FP</div>
        <div>
          <div class="brand-name">FusionPilot</div>
          <div class="brand-subtitle">&#38647;&#36798;&#20915;&#31574;&#23454;&#39564;&#23460; / &#25968;&#23383;&#23383;&#22411;</div>
        </div>
      </div>
      <div class="topbar-status">
        <span class="status-dot"></span><span>&#26412;&#22320;&#20223;&#30495;</span><span class="status-divider"></span><span>JAVA &#26680;&#24515; : 8080</span>
        <span class="status-divider"></span>
        <span v-if="authUser">{{ authUser.displayName || authUser.username }}</span>
        <template v-if="authUser">
          <button class="topbar-action" :class="{ active: activeView === 'workbench' }" @click="navigateTo('workbench')">&#23454;&#39564;&#24037;&#20316;&#21488;</button>
          <button class="topbar-action" :class="{ active: activeView === 'agent' }" @click="navigateTo('agent')">AGENT &#21161;&#25163;</button>
        </template>
        <button v-if="authUser" class="topbar-action" title="&#36864;&#20986;&#30331;&#24405;" @click="logout">&#36864;&#20986;</button>
        <template v-else>
          <button class="topbar-action" @click="openAuth('login')">&#30331;&#24405;</button>
          <button class="topbar-action accent" @click="openAuth('register')">&#27880;&#20876;</button>
        </template>
      </div>
    </header>

    <main class="workspace">
      <section v-if="!authUser" class="landing-hero">
        <div class="landing-copy">
          <p class="landing-eyebrow">FUSIONPILOT / DIGITAL BATTLESPACE</p>
          <h1>FusionPilot</h1>
          <p class="landing-title">&#19968;&#20307;&#21270;&#38647;&#36798;&#19982;&#30005;&#23376;&#23545;&#25239;&#31995;&#32479;&#25968;&#23383;&#27169;&#22411;</p>
          <p class="landing-lede">&#23558;&#38647;&#36798;&#35266;&#27979;&#12289;&#22810;&#28304;&#20449;&#24687;&#34701;&#21512;&#12289;&#36164;&#28304;&#35843;&#24230;&#19982; Agent &#23454;&#39564;&#21327;&#20316;&#32467;&#21512;&#21040;&#19968;&#20010;&#21487;&#22797;&#29616;&#30340;&#25968;&#23383;&#23454;&#39564;&#23460;&#12290;</p>
          <div class="landing-actions">
            <button class="primary-button landing-primary" @click="openAuth('login')">&#36827;&#20837;&#23454;&#39564;&#23460; <span>&rarr;</span></button>
            <button class="landing-link" @click="openAuth('register')">&#21019;&#24314;&#36134;&#21495;</button>
          </div>
          <div class="landing-facts">
            <div><strong>04</strong><span>&#26680;&#24515;&#27169;&#22359;</span></div>
            <div><strong>03</strong><span>&#35266;&#27979;&#28304;</span></div>
            <div><strong>01</strong><span>&#32479;&#19968;&#23454;&#39564;&#24037;&#20316;&#21488;</span></div>
          </div>
        </div>
        <div class="radar-stage" aria-label="FusionPilot radar visualization">
          <div class="radar-grid"></div>
          <div class="radar-scope">
            <div class="radar-ring ring-one"></div>
            <div class="radar-ring ring-two"></div>
            <div class="radar-ring ring-three"></div>
            <div class="radar-axis axis-x"></div>
            <div class="radar-axis axis-y"></div>
            <div class="radar-sweep"></div>
            <span class="radar-blip blip-one"></span>
            <span class="radar-blip blip-two"></span>
            <span class="radar-blip blip-three"></span>
            <span class="radar-core"></span>
          </div>
          <div class="radar-readout readout-top">SENSOR FUSION <strong>ONLINE</strong></div>
          <div class="radar-readout readout-bottom">TRACKS <strong>03 / 03</strong></div>
        </div>
      </section>

      <section v-if="!authUser || activeView === 'workbench'" class="intro-row">
        <div>
          <p class="eyebrow">&#22810;&#28304;&#20449;&#24687;&#34701;&#21512;</p>
          <h1>&#35266;&#27979;&#12289;&#34701;&#21512;&#19982;&#20915;&#31574;</h1>
          <p class="lede">&#36816;&#34892;&#21487;&#22797;&#29616;&#30340;&#38647;&#36798;&#36164;&#28304;&#23454;&#39564;&#65292;&#35266;&#23519;&#19981;&#30830;&#23450;&#24615;&#22914;&#20309;&#24433;&#21709;&#34701;&#21512;&#36319;&#36394;&#12290;</p>
        </div>
        <div class="run-summary"><span class="summary-label">&#36816;&#34892; ID</span><strong>{{ simulation?.runId?.slice(0, 8) ?? '--' }}</strong></div>
      </section>

      <div v-if="authModalOpen" class="auth-overlay" @click.self="authModalOpen = false">
        <section class="auth-modal panel">
          <div class="panel-heading">
            <div><span class="panel-kicker">ACCOUNT ACCESS</span><h2>{{ authMode === 'login' ? '&#30331;&#24405; FusionPilot' : authMode === 'register' ? '&#27880;&#20876; FusionPilot' : authMode === 'forgot' ? '&#25214;&#22238;&#23494;&#30721;' : '&#37325;&#32622;&#23494;&#30721;' }}</h2></div>
            <button class="icon-button" title="&#20851;&#38381;" @click="authModalOpen = false">&times;</button>
          </div>
          <div class="auth-tabs">
            <button :class="{ active: authMode === 'login' }" @click="openAuth('login')">&#30331;&#24405;</button>
            <button :class="{ active: authMode === 'register' }" @click="openAuth('register')">&#27880;&#20876;</button>
          </div>
          <form class="auth-form" @submit.prevent="authMode === 'forgot' ? submitForgot() : authMode === 'reset' ? submitReset() : submitAuth()">
            <label v-if="authMode === 'register'" class="field"><span>&#29992;&#25143;&#21517;</span><input v-model="authForm.username" required minlength="3" maxlength="50" autocomplete="username" /></label>
            <label v-if="authMode !== 'register' && authMode !== 'reset'" class="field"><span>&#29992;&#25143;&#21517;&#25110;&#37038;&#31665;</span><input v-model="authForm.login" required autocomplete="username" /></label>
            <label v-if="authMode === 'register'" class="field"><span>&#37038;&#31665;</span><input v-model="authForm.email" required type="email" autocomplete="email" /></label>
            <label v-if="authMode === 'register'" class="field"><span>&#26174;&#31034;&#21517;&#31216;</span><input v-model="authForm.displayName" required maxlength="80" /></label>
            <label v-if="authMode === 'login' || authMode === 'register'" class="field"><span>&#23494;&#30721;</span><div class="password-shell"><input v-model="authForm.password" required :minlength="authMode === 'register' ? 10 : undefined" :pattern="authMode === 'register' ? PASSWORD_PATTERN.source : undefined" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" /><button type="button" class="password-toggle" :class="{ 'is-visible': showPassword }" :title="showPassword ? '&#38544;&#34255;&#23494;&#30721;' : '&#26174;&#31034;&#23494;&#30721;'" :aria-label="showPassword ? '&#38544;&#34255;&#23494;&#30721;' : '&#26174;&#31034;&#23494;&#30721;'" @click="showPassword = !showPassword"></button></div><small v-if="authMode === 'register'" class="password-hint" :class="{ valid: passwordMeetsRules(authForm.password) }">{{ passwordHint(authForm.password) }}</small></label>
            <label v-if="authMode === 'reset'" class="field"><span>&#37325;&#32622;&#201令;&#29260;</span><input v-model="authForm.resetToken" required /></label>
            <label v-if="authMode === 'reset'" class="field"><span>&#26032;&#23494;&#30721;</span><div class="password-shell"><input v-model="authForm.newPassword" required minlength="10" :pattern="PASSWORD_PATTERN.source" :type="showNewPassword ? 'text' : 'password'" /><button type="button" class="password-toggle" :class="{ 'is-visible': showNewPassword }" :title="showNewPassword ? '&#38544;&#34255;&#23494;&#30721;' : '&#26174;&#31034;&#23494;&#30721;'" :aria-label="showNewPassword ? '&#38544;&#34255;&#23494;&#30721;' : '&#26174;&#31034;&#23494;&#30721;'" @click="showNewPassword = !showNewPassword"></button></div><small class="password-hint" :class="{ valid: passwordMeetsRules(authForm.newPassword) }">{{ passwordHint(authForm.newPassword) }}</small></label>
            <div v-if="authMode === 'login' || authMode === 'register' || authMode === 'forgot'" class="captcha-field">
              <span>&#39564;&#35777;&#30721;</span><strong>{{ captcha?.question || '--' }}</strong>
              <input v-model="captchaAnswer" required inputmode="numeric" autocomplete="off" />
              <button type="button" class="ghost-button" @click="loadCaptcha">&#25442;&#19968;&#20010;</button>
            </div>
            <button v-if="authMode === 'login'" type="button" class="auth-help" @click="openAuth('forgot')">&#24536;&#35760;&#23494;&#30721;&#65311;</button>
            <button class="primary-button auth-submit" :disabled="authBusy" type="submit">{{ authBusy ? '&#25552;&#20132;&#20013;...' : authMode === 'login' ? '&#30331;&#24405;' : authMode === 'register' ? '&#21019;&#24314;&#36134;&#21495;' : authMode === 'forgot' ? '&#21457;&#36865;&#37325;&#32622;&#35831;&#27714;' : '&#20445;&#23384;&#26032;&#23494;&#30721;' }}</button>
          </form>
          <p v-if="authMessage" class="auth-message">{{ authMessage }}</p>
          <p v-if="authError" class="auth-error">{{ authError }}</p>
        </section>
      </div>

      <div v-if="authUser && errorMessage" class="alert">
        <span>{{ errorMessage }}</span>
        <button class="icon-button" title="&#20851;&#38381;&#25552;&#31034;" @click="errorMessage = ''">&times;</button>
      </div>

      <section v-if="authUser && activeView === 'workbench'" class="dashboard-grid">
        <aside class="panel config-panel">
          <div class="panel-heading">
            <div><span class="panel-kicker">01 / &#22330;&#26223;</span><h2>&#23454;&#39564;&#37197;&#32622;</h2></div>
            <button class="ghost-button" :disabled="loadingConfig" @click="loadDefaultConfig">{{ loadingConfig ? '\u52a0\u8f7d\u4e2d...' : '\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f' }}</button>
          </div>

          <div class="scene-state" :class="{ ready: sceneLoaded }">
            <span>{{ sceneLoaded ? '\u573a\u666f\u5df2\u52a0\u8f7d' : '\u8bf7\u5148\u52a0\u8f7d\u573a\u666f' }}</span>
          </div>

          <label class="field"><span>&#22330;&#26223;&#21517;&#31216;</span><input v-model="config.scenarioName" /></label>
          <div class="field-grid">
            <label class="field"><span>&#30446;&#26631;&#25968;&#37327;</span><input v-model.number="config.targetCount" type="number" min="1" max="10" /></label>
            <label class="field"><span>&#36164;&#28304;&#25968;&#37327;</span><input v-model.number="config.availableResources" type="number" min="1" max="10" /></label>
            <label class="field"><span>&#26102;&#38388;&#27493;&#25968;</span><input v-model.number="config.simulationSteps" type="number" min="1" max="60" /></label>
            <label class="field"><span>&#38543;&#26426;&#31181;&#23376;</span><input v-model.number="config.randomSeed" type="number" /></label>
          </div>

          <label class="field">
            <span>&#35843;&#24230;&#31574;&#30053;</span>
            <select v-model="config.schedulingPolicy">
              <option value="ROUND_ROBIN">&#36718;&#35810;&#35843;&#24230;</option>
              <option value="PRIORITY">&#20248;&#20808;&#32423;&#35843;&#24230;</option>
            </select>
          </label>

          <div class="source-list">
            <div class="subsection-title">&#35266;&#27979;&#28304;</div>
            <div v-for="source in config.observationSources" :key="source.type" class="source-row">
              <div><strong>{{ sourceLabel(source.type) }}</strong><small>&#22122;&#22768; {{ source.noiseStdDev }} / &#32570;&#22833; {{ Math.round(source.missingRate * 100) }}%</small></div>
              <span class="source-confidence">{{ Math.round(source.confidence * 100) }}%</span>
            </div>
          </div>

          <div v-if="loading || progressText" class="run-progress">
            <div class="progress-heading">
              <span>{{ progressText }}</span>
              <strong>{{ progressPercent }}%</strong>
            </div>
            <div class="progress-track"><span :style="{ width: `${progressPercent}%` }"></span></div>
            <button type="button" v-if="loading" class="cancel-button" @click.stop.prevent="cancelRun">&#20572;&#27490;&#31561;&#24453;</button>
          </div>

          <div class="action-stack">
            <button class="primary-button" :disabled="!canRun" @click="runSimulation"><span class="button-icon">&gt;</span>{{ loading ? '\u8fd0\u884c\u4e2d...' : '\u8fd0\u884c\u4eff\u771f' }}</button>
            <button class="secondary-button" :disabled="!canRun" @click="comparePolicies"><span class="button-icon">&lt;&gt;</span>&#23545;&#27604;&#35843;&#24230;&#31574;&#30053;</button>
          </div>
        </aside>

        <section class="main-column">
          <div class="metrics-grid">
            <div class="metric-card"><span class="metric-label">&#20301;&#32622;&#35823;&#24046;</span><strong>{{ formatNumber(activeMetrics?.averagePositionError) }}</strong><small>&#24179;&#22343;&#27431;&#27663;&#36317;&#31163;</small></div>
            <div class="metric-card accent-cyan"><span class="metric-label">&#36319;&#36394;&#29575;</span><strong>{{ activeMetrics ? `${formatNumber(activeMetrics.trackingRate * 100, 1)}%` : '--' }}</strong><small>&#34701;&#21512;&#29366;&#24577;&#21344;&#27604;</small></div>
            <div class="metric-card accent-amber"><span class="metric-label">&#36164;&#28304;&#21033;&#29992;&#29575;</span><strong>{{ activeMetrics ? `${formatNumber(activeMetrics.resourceUtilization * 100, 1)}%` : '--' }}</strong><small>&#24050;&#20998;&#37197;&#20219;&#21153;&#27133;&#20301;</small></div>
            <div class="metric-card accent-violet"><span class="metric-label">&#24179;&#22343;&#31561;&#24453;</span><strong>{{ formatNumber(activeMetrics?.averageWaitingTime) }}</strong><small>&#26410;&#26381;&#21153;&#26102;&#38388;&#27493;</small></div>
          </div>

          <div class="panel chart-panel">
            <div class="panel-heading"><div><span class="panel-kicker">02 / &#36712;&#36857;</span><h2>&#30495;&#23454;&#29366;&#24577;&#19982;&#34701;&#21512;&#29366;&#24577;</h2></div><div class="legend-note"><span class="line-sample"></span>&#34394;&#32447;&#65309;&#34701;&#21512;&#20272;&#35745;</div></div>
            <div v-if="!simulation" class="empty-state"><div class="empty-orbit"></div><strong>{{ sceneLoaded ? '\u573a\u666f\u5df2\u5c31\u7eea' : '\u7b49\u5f85\u52a0\u8f7d\u573a\u666f' }}</strong><span>{{ sceneLoaded ? '\u70b9\u51fb\u8fd0\u884c\u4eff\u771f\u751f\u6210\u8f68\u8ff9\u548c\u6307\u6807\u3002' : '\u5148\u70b9\u51fb\u5de6\u4fa7\u7684\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f\u3002' }}</span></div>
            <div v-else ref="chartElement" class="chart"></div>
          </div>

          <div class="lower-grid">
            <div class="panel step-panel">
              <div class="panel-heading compact"><div><span class="panel-kicker">03 / &#22238;&#25918;</span><h2>&#26102;&#38388;&#27493;&#26597;&#30475;</h2></div><span class="step-counter">{{ currentStep ? `${currentStep.timeStep + 1} / ${simulation?.steps.length}` : '--' }}</span></div>
              <input v-if="simulation" v-model.number="activeStep" class="range" type="range" min="0" :max="Math.max(0, simulation.steps.length - 1)" />
              <div v-if="currentStep" class="step-details">
                <div class="detail-chip"><span class="detail-label">&#26377;&#25928;&#35266;&#27979;</span><strong>{{ currentStep.observations.filter((item) => item.available).length }}</strong></div>
                <div class="detail-chip"><span class="detail-label">&#24050;&#20998;&#37197;&#30446;&#26631;</span><strong>{{ currentStep.scheduling.allocatedTargetIds.join(', ') || '\u65e0' }}</strong></div>
                <div class="detail-chip"><span class="detail-label">&#24403;&#27493;&#35823;&#24046;</span><strong>{{ formatNumber(currentStep.metrics.averagePositionError) }}</strong></div>
              </div>
            </div>

            <div class="panel schedule-panel">
              <div class="panel-heading compact"><div><span class="panel-kicker">04 / &#36164;&#28304;&#26085;&#24535;</span><h2>&#26368;&#36817;&#20998;&#37197;</h2></div><span class="policy-tag">{{ simulation?.config.schedulingPolicy ?? '--' }}</span></div>
              <div v-if="visibleSteps.length" class="schedule-list">
                <div v-for="step in visibleSteps" :key="step.timeStep" class="schedule-row"><span class="time-index">T{{ step.timeStep }}</span><div class="allocation-bar"><span v-for="targetId in config.targetCount" :key="targetId" :class="{ active: step.scheduling.allocatedTargetIds.includes(targetId) }"></span></div><span class="allocation-count">{{ step.scheduling.allocatedTargetIds.length }}/{{ config.availableResources }}</span></div>
              </div>
              <div v-else class="muted-empty">&#36816;&#34892;&#20223;&#30495;&#21518;&#26174;&#31034;&#36164;&#28304;&#20998;&#37197;&#35760;&#24405;&#12290;</div>
            </div>
          </div>

          <div v-if="comparison" class="panel comparison-panel">
            <div class="panel-heading compact"><div><span class="panel-kicker">05 / &#31574;&#30053;&#24046;&#24322;</span><h2>&#20248;&#20808;&#32423;&#35843;&#24230; - &#36718;&#35810;&#35843;&#24230;</h2></div><span class="policy-tag">&#23545;&#27604;&#23436;&#25104;</span></div>
            <div class="delta-grid">
              <div><span>&#20301;&#32622;&#35823;&#24046;&#24046;&#20540;</span><strong>{{ formatNumber(comparison.priorityMinusRoundRobin.averagePositionErrorDelta) }}</strong></div>
              <div><span>&#36319;&#36394;&#29575;&#24046;&#20540;</span><strong>{{ formatNumber(comparison.priorityMinusRoundRobin.trackingRateDelta * 100, 1) }}%</strong></div>
              <div><span>&#31561;&#24453;&#26102;&#38388;&#24046;&#20540;</span><strong>{{ formatNumber(comparison.priorityMinusRoundRobin.averageWaitingTimeDelta) }}</strong></div>
              <div><span>&#20999;&#25442;&#27425;&#25968;&#24046;&#20540;</span><strong>{{ comparison.priorityMinusRoundRobin.schedulingSwitchesDelta }}</strong></div>
            </div>
          </div>
        </section>
      </section>
      <section v-if="authUser && activeView === 'agent'" class="agent-page">
        <div class="agent-page-hero">
          <div>
            <p class="eyebrow">FUSIONPILOT / RESEARCH COPILOT</p>
            <h1>&#38647;&#36798;&#19982;&#30005;&#23376;&#23545;&#25239;&#21327;&#21516;&#21161;&#25163;</h1>
            <p class="lede">&#25226;&#35266;&#27979;&#28304;&#12289;&#20449;&#24687;&#34701;&#21512;&#12289;&#36164;&#28304;&#35843;&#24230;&#21644;&#25239;&#24178;&#25200;&#25351;&#26631;&#20018;&#25104;&#19968;&#20010;&#21487;&#23457;&#38405;&#30340;&#23454;&#39564;&#38381;&#29615;&#12290; Agent &#21482;&#25552;&#20986;&#21644;&#35299;&#37322;&#65292;&#20223;&#30495;&#20107;&#23454;&#27704;&#36828;&#26469;&#33258; Java &#26680;&#24515;&#12290;</p>
          </div>
          <div class="agent-model-status">
            <span class="panel-kicker">ACTIVE MODEL</span>
            <strong>{{ selectedProviderLabel }}</strong>
            <span>{{ selectedModelName }}</span>
            <em>{{ selectedProviderInfo?.configured || selectedAgentProvider === 'rule' ? 'READY' : 'UNCONFIGURED / RULE FALLBACK' }}</em>
          </div>
        </div>
        <div class="agent-page-grid">
          <section class="panel agent-command-panel">
            <div class="panel-heading">
              <div><span class="panel-kicker">01 / MISSION BRIEF</span><h2>&#23454;&#39564;&#20219;&#21153;&#31616;&#25253;</h2></div>
              <span class="policy-tag">{{ agentSession?.status ?? '&#24453;&#21019;&#24314;' }}</span>
            </div>
            <p class="agent-domain-note">&#20320;&#21487;&#20197;&#35201;&#27714; Agent &#35268;&#21010;&#38647;&#36798;&#35266;&#27979;&#12289;&#20809;&#30005;/&#32418;&#22806;&#35266;&#27979;&#12289;&#20808;&#39564;&#20449;&#24687;&#30340;&#34701;&#21512;&#26041;&#26696;&#65292;&#25110;&#22312;&#24178;&#25200;&#21644;&#36164;&#28304;&#21463;&#38480;&#26102;&#20248;&#21270;&#35843;&#24230;&#31574;&#30053;&#12290;</p>
            <div class="agent-model-picker">
              <label class="field">
                <span>&#27169;&#22411;&#25552;&#20379;&#26041;</span>
                <select v-model="selectedAgentProvider" @change="handleAgentProviderChange">
                  <option value="rule">&#26412;&#22320;&#35268;&#21017;</option>
                  <option v-for="provider in agentModelStatus?.providers ?? []" :key="provider.provider" :value="provider.provider">{{ provider.label }}</option>
                </select>
              </label>
              <label class="field">
                <span>&#27169;&#22411;&#21517;&#31216;</span>
                <select v-model="selectedAgentModel" :disabled="selectedAgentProvider === 'rule'">
                  <option v-for="model in selectedModelOptions" :key="model" :value="selectedAgentProvider === 'rule' ? '' : model">{{ model }}</option>
                </select>
              </label>
              <div class="model-state" :class="{ ready: selectedProviderInfo?.configured || selectedAgentProvider === 'rule' }">
                <span>{{ selectedAgentProvider === 'rule' ? 'LOCAL' : selectedProviderInfo?.configured ? 'API READY' : 'NEEDS API KEY' }}</span>
                <strong>{{ selectedAgentProvider === 'rule' ? '&#35268;&#21017;&#27169;&#24335;' : selectedProviderInfo?.protocol ?? '--' }}</strong>
              </div>
            </div>
            <label class="field agent-goal">
              <span>&#30740;&#31350;&#20219;&#21153;</span>
              <textarea v-model="agentGoal" rows="7" placeholder="&#20363;&#22914;&#65306;&#22312;&#38647;&#36798;&#22122;&#22768;&#22686;&#22823;&#19988;&#20809;&#30005;&#35266;&#27979;&#32570;&#22833;&#26102;&#65292;&#27604;&#36739;&#20004;&#31181;&#35843;&#24230;&#31574;&#30053;&#23545;&#36319;&#36394;&#29575;&#21644;&#36164;&#28304;&#21033;&#29992;&#29575;&#30340;&#24433;&#21709;"></textarea>
            </label>
            <div class="agent-actions">
              <button class="secondary-button" :disabled="agentBusy || !agentGoal.trim()" @click="createAgentSession">&#29983;&#25104;&#23454;&#39564;&#26041;&#26696;</button>
              <button class="secondary-button" :disabled="agentBusy || !agentSession || agentSession.confirmed" @click="confirmAgentSession">&#23457;&#38405;&#21518;&#30830;&#35748;</button>
            </div>
            <div v-if="agentSession" class="agent-tool-row">
              <select v-model="agentTool" :disabled="agentBusy || !agentSession.confirmed">
                <option value="validate_experiment">&#26816;&#26597;&#20223;&#30495;&#37197;&#32622;</option>
                <option value="run_simulation">&#25191;&#34892;&#38647;&#36798;&#20223;&#30495;</option>
                <option value="calculate_metrics">&#25552;&#21462;&#25239;&#24178;&#25200;&#25351;&#26631;</option>
                <option value="compare_scheduling_policies">&#27604;&#36739;&#36164;&#28304;&#35843;&#24230;</option>
              </select>
              <button class="primary-button" :disabled="agentBusy || !agentSession.confirmed" @click="executeAgentTool">&#25191;&#34892;&#24037;&#20855;</button>
            </div>
            <p v-if="agentMessage" class="agent-message">{{ agentMessage }}</p>
            <p v-if="agentError" class="agent-error">{{ agentError }}</p>
            <div class="agent-capability-grid">
              <div><strong>01</strong><span>&#35266;&#27979;&#28304;</span><small>RADAR / EO-IR / PRIOR</small></div>
              <div><strong>02</strong><span>&#20449;&#24687;&#34701;&#21512;</span><small>CONFIDENCE / PREDICTION</small></div>
              <div><strong>03</strong><span>&#36164;&#28304;&#35843;&#24230;</span><small>ROUND ROBIN / PRIORITY</small></div>
              <div><strong>04</strong><span>&#21453;&#24178;&#25200;&#35780;&#20272;</span><small>NOISE / MISSING / DELAY</small></div>
            </div>
          </section>
          <section class="panel agent-plan-panel">
            <div class="panel-heading">
              <div><span class="panel-kicker">02 / PLAN REVIEW</span><h2>&#21487;&#23457;&#38405;&#30340;&#23454;&#39564;&#26041;&#26696;</h2></div>
              <span v-if="agentSession" class="policy-tag">{{ agentSession.plan.planner || 'RULE' }}</span>
            </div>
            <div v-if="agentSession">
              <div class="agent-plan-title">{{ agentSession.plan.title }}</div>
              <div class="agent-plan-grid">
                <div><span>&#22522;&#32447;</span><strong>{{ agentSession.plan.baselines.join(' / ') }}</strong></div>
                <div><span>&#25351;&#26631;</span><strong>{{ agentSession.plan.metrics.length }} &#39033;</strong></div>
                <div><span>&#27169;&#22411;</span><strong>{{ agentSession.plan.model || 'LOCAL RULES' }}</strong></div>
              </div>
              <ol class="agent-steps">
                <li v-for="step in agentSession.plan.execution_steps" :key="step">{{ step }}</li>
              </ol>
              <button class="ghost-button trace-button" @click="refreshAgentTrace">&#21047;&#26032;&#36712;&#36857;</button>
            </div>
            <div v-else class="agent-empty">&#25552;&#20132;&#19968;&#20010;&#38647;&#36798;&#19982;&#30005;&#23376;&#23545;&#25239;&#23454;&#39564;&#20219;&#21153;&#65292;Agent &#20250;&#20808;&#35299;&#26512;&#35266;&#27979;&#21644;&#35843;&#24230;&#26465;&#20214;&#12290;</div>
          </section>
        </div>
        <div class="agent-page-grid agent-lower-grid">
          <section class="panel agent-trace-panel">
            <div class="panel-heading compact"><div><span class="panel-kicker">03 / TOOL TRACE</span><h2>&#21327;&#21516;&#25191;&#34892;&#36712;&#36857;</h2></div><span class="step-counter">{{ agentSession?.events.length ?? 0 }} EVENTS</span></div>
            <div v-if="agentSession?.events.length" class="agent-event-list">
              <div v-for="event in agentSession.events" :key="event.event_id" class="agent-event-row">
                <span class="event-mark"></span><div><strong>{{ event.event_type }}</strong><small>{{ event.created_at }}</small></div>
              </div>
            </div>
            <div v-else class="muted-empty">&#31561;&#24453; Agent &#21019;&#24314;&#20219;&#21153;&#24182;&#35760;&#24405;&#35266;&#27979;&#12289;&#34701;&#21512;&#21644;&#35843;&#24230;&#24037;&#20855;&#35843;&#29992;&#12290;</div>
          </section>
          <section class="panel agent-evidence-panel">
            <div class="panel-heading compact"><div><span class="panel-kicker">04 / EVIDENCE</span><h2>&#32467;&#26500;&#21270;&#35777;&#25454;</h2></div><span class="policy-tag">{{ agentResult ? '&#24050;&#36820;&#22238;' : '--' }}</span></div>
            <div v-if="agentResult?.analysis" class="agent-analysis">
              <p>{{ agentResult.analysis.summary }}</p>
              <div class="agent-evidence"><span v-for="item in agentResult.analysis.evidence" :key="item.metric" class="evidence-chip">{{ item.metric }}: {{ item.value }}</span></div>
              <ul class="agent-limitations"><li v-for="item in agentResult.analysis.limitations" :key="item">{{ item }}</li></ul>
            </div>
            <div v-else class="muted-empty">&#25191;&#34892;&#24037;&#20855;&#21518;&#65292;&#36825;&#37324;&#20250;&#23637;&#31034;&#36319;&#36394;&#29575;&#12289;&#20301;&#32622;&#35823;&#24046;&#12289;&#36164;&#28304;&#21033;&#29992;&#29575;&#21644;&#31574;&#30053;&#24046;&#24322;&#12290;</div>
          </section>
        </div>
      </section>
    </main>
  </div>
</template>
