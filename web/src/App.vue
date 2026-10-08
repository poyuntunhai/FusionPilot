<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

type SimulationJobStatus = {
  jobId: string
  status: 'QUEUED' | 'RUNNING' | 'CANCELLING' | 'CANCELLED' | 'COMPLETED' | 'FAILED'
  progressPercent: number
  completedSteps: number
  totalSteps: number
  message: string
  runId: string | null
  result: SimulationResult | null
}

/** One entry of the signed-in user's saved history, as returned by GET /simulations/history. */
type SavedRunSummary = {
  runId: string
  scenarioName: string
  targetCount: number
  simulationSteps: number
  schedulingPolicy: string
  fusionMethod: string
  randomSeed: number
  averagePositionError: number
  trackingRate: number
  resourceUtilization: number
  averageWaitingTime: number
  schedulingSwitches: number
  totalSteps: number
  completedAt: string
  savedAt: string
}

/** Response of POST /simulations/{runId}/save. */
type SaveRunResult = {
  runId: string
  saved: boolean
  savedCount: number
  savedLimit: number
  evictedRunIds: string[]
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
  /** Tool the plan says should run next; the UI preselects it. */
  recommended_tool?: AgentToolName | null
  /** Set when a model was requested but the local rule planner answered instead. */
  planning_note?: string | null
}

type AgentAnalysis = {
  summary: string
  metrics: Record<string, unknown>
  evidence: Array<{ metric: string; value: unknown; source: string; note?: string }>
  limitations: string[]
  /** "rule" or "<provider>:<model>" — who produced the reading. */
  produced_by?: string
}

type AgentToolCall = {
  call_id: string
  name: string
  arguments: Record<string, unknown>
}

type AgentChatMessage = {
  message_id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  tool_calls: AgentToolCall[]
  tool_call_id: string | null
  tool_name: string | null
  tool_ok: boolean | null
  evidence: Array<{ metric: string; value: unknown; source?: string }>
  limitations: string[]
  run_id: string | null
  /** Knowledge sections this answer was grounded in; absent on snapshots stored before this existed. */
  knowledge?: Array<{ chunk_id: string; doc: string; title: string; score: number }>
  /** "<provider>:<model>" for a model turn, "rule" when the local planner answered. */
  produced_by: string | null
  created_at: string
}

type AgentPendingDecision = {
  tool_calls: AgentToolCall[]
  prompt: string
  created_at: string
}

type AgentPlanStep = {
  summary: string
  tool: string
  arguments: Record<string, unknown>
}

type AgentExperimentSequence = {
  goal: string
  rationale: string
  steps: AgentPlanStep[]
  produced_by: string
}

type AgentConversation = {
  session_id: string
  title: string
  status: string
  provider: string
  model: string | null
  auto_approve: boolean
  messages: AgentChatMessage[]
  events: Array<{
    event_id: string
    event_type: string
    payload: Record<string, unknown>
    created_at: string
  }>
  working_config: Record<string, unknown>
  pending: AgentPendingDecision | null
  sequence: AgentExperimentSequence | null
  /** Present once a run has been read; absent on snapshots stored before the analyser existed. */
  analysis?: AgentAnalysis | null
  last_run_id: string | null
  last_evidence: Array<{ metric: string; value: unknown }>
  last_limitations: string[]
  tool_call_count: number
  created_at: string
  updated_at: string
}

type AgentConversationSummary = {
  session_id: string
  title: string
  status: string
  provider: string
  model: string | null
  message_count: number
  tool_call_count: number
  working_summary: string
  created_at: string
  updated_at: string
}
type AuthUser = {
  userId: number
  username: string
  email: string
  displayName: string
  role: string
  status: string
}

type DatasetImportSummary = {
  datasetId: string
  fileName: string
  fileSize: number
  status: string
  truthRows: number
  observationRows: number
  errors: string[]
  warnings: string[]
  createdAt: string
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
type AgentToolName =
  | 'validate_experiment'
  | 'run_simulation'
  | 'calculate_metrics'
  | 'compare_scheduling_policies'

type AgentModelStatus = {
  current: {
    provider: string
    label: string
    protocol: string
    model: string | null
    configured: boolean
    serverConfigured?: boolean
    fallbackToRule: boolean
  }
  providers: Array<{
    provider: string
    label: string
    protocol: string
    defaultModel: string
    modelOptions: string[]
    freeModels?: string[]
    configured: boolean
    serverConfigured?: boolean
  }>
  /** True when this browser supplied its own token with the request. */
  hasRequestKey?: boolean
}

type AgentConnectionTest = {
  provider: string
  label: string
  model: string
  reply: string
}

// Mirrors ExperimentConfigService.defaultConfig() so a stale or unloadable scene still has a
// valid starting point, and gives the "restore defaults" control something to restore.
const DEFAULT_OBSERVATION_SOURCES: ObservationSource[] = [
  { type: 'RADAR', noiseStdDev: 3, missingRate: 0.05, delaySteps: 0, confidence: 0.9 },
  { type: 'EO_IR', noiseStdDev: 5, missingRate: 0.15, delaySteps: 1, confidence: 0.75 },
  { type: 'PRIOR_KNOWLEDGE', noiseStdDev: 8, missingRate: 0.25, delaySteps: 0, confidence: 0.55 }
]

function cloneDefaultObservationSources(): ObservationSource[] {
  return DEFAULT_OBSERVATION_SOURCES.map((source) => ({ ...source }))
}

const config = ref<ExperimentConfig>({
  scenarioName: 'multi-target-demo',
  targetCount: 3,
  simulationSteps: 100,
  timeStepSeconds: 1,
  availableResources: 2,
  fusionMethod: 'WEIGHTED_AVERAGE',
  schedulingPolicy: 'ROUND_ROBIN',
  randomSeed: 20260928,
  observationSources: cloneDefaultObservationSources()
})

const simulation = ref<SimulationResult | null>(null)
const comparison = ref<ComparisonResult | null>(null)
const sceneLoaded = ref(false)
const loading = ref(false)
const loadingConfig = ref(false)
const errorMessage = ref('')

const savedRuns = ref<SavedRunSummary[]>([])
const historyLoading = ref(false)
const historyMessage = ref('')
const savedRunIds = computed(() => new Set(savedRuns.value.map((entry) => entry.runId)))
const currentRunSaved = computed(() => (
  simulation.value !== null && savedRunIds.value.has(simulation.value.runId)
))
const HISTORY_LIMIT = 10
const progressPercent = ref(0)
const progressText = ref('')
const activeStep = ref(0)
const cancelling = ref(false)
const playbackPlaying = ref(false)
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
const datasetFile = ref<File | null>(null)
const datasetBusy = ref(false)
const datasetMessage = ref('')
const datasetSummary = ref<DatasetImportSummary | null>(null)
let chart: echarts.ECharts | null = null
let playbackTimer: number | undefined
let chartRenderFrame: number | undefined
const REQUEST_TIMEOUT_MS = 30_000
const RUN_WATCHDOG_MS = 32_000
const PASSWORD_PATTERN = /^(?=.{10,100}$)(?:(?=.*[A-Za-z])(?=.*\d)|(?=.*[A-Za-z])(?=.*[^A-Za-z\d])|(?=.*\d)(?=.*[^A-Za-z\d])).*$/

const activeMetrics = computed(() => simulation.value?.metrics ?? null)
const currentStep = computed(() => simulation.value?.steps[activeStep.value] ?? null)
const visibleSteps = computed(() => simulation.value?.steps.slice(0, activeStep.value + 1).slice(-12).reverse() ?? [])
const resourceSlots = computed(() => {
  const count = simulation.value?.config.targetCount ?? config.value.targetCount
  return Array.from({ length: Math.max(0, Math.min(count, 20)) }, (_, index) => index + 1)
})
// Mirrors the FusionMethod enum on the backend. Every entry runs a real, distinct algorithm.
const fusionMethodOptions = [
  { value: 'WEIGHTED_AVERAGE', label: '\u7f6e\u4fe1\u5ea6\u52a0\u6743\u5e73\u5747' },
  { value: 'SIMPLE_AVERAGE', label: '\u7b49\u6743\u5e73\u5747' },
  { value: 'NEAREST_NEIGHBOR', label: '\u6700\u8fd1\u90bb\uff08\u53d6\u6700\u63a5\u8fd1\u9884\u6d4b\u7684\u4e00\u4e2a\uff09' },
  { value: 'DISTANCE_GATED', label: '\u8ddd\u79bb\u95e8\u9650 + \u52a0\u6743\u5e73\u5747' },
  { value: 'KALMAN_FILTER', label: '\u5361\u5c14\u66fc\u6ee4\u6ce2\uff08\u5300\u901f\u6a21\u578b\uff09' }
]

function isIntegerInRange(value: unknown, min: number, max: number): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max
}

// Mirrors the Bean Validation constraints on ExperimentConfig, so an out-of-range value is
// explained next to the field instead of coming back as a raw 400 from the backend.
const configIssues = computed<string[]>(() => {
  const current = config.value
  const issues: string[] = []
  if (!current.scenarioName?.trim()) {
    issues.push('\u573a\u666f\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a')
  } else if (current.scenarioName.length > 80) {
    issues.push('\u573a\u666f\u540d\u79f0\u4e0d\u80fd\u8d85\u8fc7 80 \u4e2a\u5b57\u7b26')
  }
  if (!isIntegerInRange(current.targetCount, 1, 50)) issues.push('\u76ee\u6807\u6570\u91cf\u9700\u4e3a 1\u201350 \u7684\u6574\u6570')
  if (!isIntegerInRange(current.availableResources, 1, 50)) issues.push('\u8d44\u6e90\u6570\u91cf\u9700\u4e3a 1\u201350 \u7684\u6574\u6570')
  if (!isIntegerInRange(current.simulationSteps, 1, 10000)) issues.push('\u65f6\u95f4\u6b65\u6570\u9700\u4e3a 1\u201310000 \u7684\u6574\u6570')
  if (!Number.isFinite(current.timeStepSeconds) || current.timeStepSeconds < 0.01) {
    issues.push('\u65f6\u95f4\u6b65\u957f\u9700\u4e0d\u5c0f\u4e8e 0.01 \u79d2')
  }
  if (!Number.isFinite(current.randomSeed)) issues.push('\u968f\u673a\u79cd\u5b50\u9700\u4e3a\u6574\u6570')
  if (!current.observationSources.length) issues.push('\u81f3\u5c11\u9700\u8981\u4e00\u4e2a\u89c2\u6d4b\u6e90')

  for (const source of current.observationSources) {
    const label = sourceLabel(source.type)
    if (!Number.isFinite(source.noiseStdDev) || source.noiseStdDev < 0) {
      issues.push(`${label}\uff1a\u566a\u58f0\u4e0d\u80fd\u4e3a\u8d1f`)
    }
    if (!Number.isFinite(source.missingRate) || source.missingRate < 0 || source.missingRate > 1) {
      issues.push(`${label}\uff1a\u7f3a\u5931\u7387\u9700\u5728 0\u2013100% \u4e4b\u95f4`)
    }
    if (!isIntegerInRange(source.delaySteps, 0, 10)) {
      issues.push(`${label}\uff1a\u5ef6\u8fdf\u9700\u4e3a 0\u201310 \u7684\u6574\u6570\u6b65`)
    }
    if (!Number.isFinite(source.confidence) || source.confidence < 0.1 || source.confidence > 1) {
      issues.push(`${label}\uff1a\u7f6e\u4fe1\u5ea6\u9700\u5728 10%\u2013100% \u4e4b\u95f4`)
    }
  }
  return issues
})

// Legal configurations that are still worth flagging before a long run.
const configHints = computed<string[]>(() => {
  const current = config.value
  const hints: string[] = []
  if (
    isIntegerInRange(current.availableResources, 1, 50)
    && isIntegerInRange(current.targetCount, 1, 50)
    && current.availableResources > current.targetCount
  ) {
    const wasted = current.availableResources - current.targetCount
    hints.push(`\u8d44\u6e90\u69fd\u4f4d\u591a\u4e8e\u76ee\u6807\u6570\u91cf\uff0c\u6bcf\u6b65\u6709 ${wasted} \u4e2a\u69fd\u4f4d\u4f1a\u7a7a\u7f6e`)
  }
  const delayed = current.observationSources.filter((source) => source.delaySteps > 0)
  if (delayed.length) {
    hints.push(`${delayed.map((source) => sourceLabel(source.type)).join('\u3001')} \u62a5\u544a\u7684\u662f\u82e5\u5e72\u6b65\u4e4b\u524d\u7684\u4f4d\u7f6e\uff0c\u5c5e\u4e8e\u771f\u5b9e\u89c2\u6d4b\u6ede\u540e`)
  }
  if (isIntegerInRange(current.simulationSteps, 1, 10000) && current.simulationSteps > 1000) {
    hints.push('\u6b65\u6570\u8f83\u5927\uff0c\u8fd0\u884c\u4e0e\u56fe\u8868\u6e32\u67d3\u90fd\u4f1a\u66f4\u6162')
  }
  return hints
})

const canRun = computed(() => (
  sceneLoaded.value
  && configIssues.value.length === 0
  && !loading.value
  && !cancelling.value
  && !loadingConfig.value
))
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
const freeModels = computed(() => new Set(selectedProviderInfo.value?.freeModels ?? []))
function isFreeModel(model: string) {
  return freeModels.value.has(model)
}
const selectedModelIsFree = computed(() => isFreeModel(selectedModelName.value))

const modelDropdownOpen = ref(false)
const modelSearch = ref('')
const filteredModelOptions = computed(() => {
  const query = modelSearch.value.trim().toLowerCase()
  const options = selectedModelOptions.value
  if (!query) return options
  return options.filter((model) => model.toLowerCase().includes(query))
})
function toggleModelDropdown() {
  if (selectedAgentProvider.value === 'rule') return
  modelDropdownOpen.value = !modelDropdownOpen.value
  if (modelDropdownOpen.value) modelSearch.value = ''
}
function closeModelDropdown() {
  modelDropdownOpen.value = false
  modelSearch.value = ''
}
function pickModel(name: string) {
  if (!name) return
  selectedAgentModel.value = name
  closeModelDropdown()
}
function onDocumentClick(event: MouseEvent) {
  if (!modelDropdownOpen.value) return
  if ((event.target as HTMLElement).closest('.model-select')) return
  closeModelDropdown()
}

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

function oneDecimal(value: number) {
  return Number.isFinite(value) ? value.toFixed(1) : '--'
}

function resetObservationSources() {
  config.value.observationSources = cloneDefaultObservationSources()
}

function fusionMethodLabel(value: string) {
  return fusionMethodOptions.find((option) => option.value === value)?.label ?? value
}

function formatTimestamp(value: string) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime()) || date.getUTCFullYear() < 2000) return '--'
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function loadSavedHistory() {
  if (!authUser.value) {
    savedRuns.value = []
    return
  }
  historyLoading.value = true
  try {
    savedRuns.value = await request<SavedRunSummary[]>(`/api/v1/simulations/history?limit=${HISTORY_LIMIT}`)
    historyMessage.value = ''
  } catch (error) {
    historyMessage.value = '\u5386\u53f2\u8bb0\u5f55\u52a0\u8f7d\u5931\u8d25\uff1a' + String(error)
  } finally {
    historyLoading.value = false
  }
}

async function saveCurrentRun() {
  const result = simulation.value
  if (!result || currentRunSaved.value) return
  try {
    const saved = await request<SaveRunResult>(
      `/api/v1/simulations/${result.runId}/save`,
      { method: 'POST' }
    )
    await loadSavedHistory()
    historyMessage.value = saved.evictedRunIds.length
      ? `\u5df2\u4fdd\u5b58\u3002\u5386\u53f2\u4e0a\u9650 ${saved.savedLimit} \u6761\uff0c\u6700\u65e7\u7684 ${saved.evictedRunIds.length} \u6761\u5df2\u88ab\u79fb\u9664\u3002`
      : `\u5df2\u4fdd\u5b58\uff08${saved.savedCount}/${saved.savedLimit}\uff09\u3002`
  } catch (error) {
    errorMessage.value = '\u4fdd\u5b58\u5931\u8d25\uff1a' + String(error)
  }
}

async function loadSavedRun(entry: SavedRunSummary) {
  // Loading a stored run replaces whatever the workbench is showing, so stop anything in flight.
  activeRunToken.value += 1
  activeController.value?.abort()
  activeController.value = null
  stopPlayback()
  loading.value = false
  cancelling.value = false
  try {
    const stored = normalizeSimulationResult(
      await request<SimulationResult>(`/api/v1/simulations/${entry.runId}`)
    )
    simulation.value = stored
    comparison.value = null
    config.value = stored.config
    sceneLoaded.value = true
    activeStep.value = Math.max(0, stored.steps.length - 1)
    progressText.value = `\u5df2\u8f7d\u5165\u5386\u53f2\u8bb0\u5f55\uff1a${entry.scenarioName}`
    progressPercent.value = 100
    await nextTick()
    renderChart()
  } catch (error) {
    errorMessage.value = '\u8f7d\u5165\u5386\u53f2\u8bb0\u5f55\u5931\u8d25\uff1a' + String(error)
  }
}

async function deleteSavedRun(entry: SavedRunSummary) {
  try {
    await request(`/api/v1/simulations/${entry.runId}/save`, { method: 'DELETE' })
    // The result may still be on screen; only the history entry goes away.
    await loadSavedHistory()
    historyMessage.value = '\u5df2\u4ece\u5386\u53f2\u8bb0\u5f55\u4e2d\u79fb\u9664\u3002'
  } catch (error) {
    errorMessage.value = '\u79fb\u9664\u5931\u8d25\uff1a' + String(error)
  }
}

function finishProgress(text: string) {
  progressPercent.value = 100
  progressText.value = text
}

function stopPlayback() {
  if (playbackTimer !== undefined) {
    window.clearInterval(playbackTimer)
    playbackTimer = undefined
  }
  playbackPlaying.value = false
}

function togglePlayback() {
  if (!simulation.value) return
  if (playbackTimer !== undefined) {
    stopPlayback()
    return
  }
  if (activeStep.value >= simulation.value.steps.length - 1) {
    activeStep.value = 0
  }
  playbackPlaying.value = true
  playbackTimer = window.setInterval(() => {
    if (!simulation.value || activeStep.value >= simulation.value.steps.length - 1) {
      stopPlayback()
      return
    }
    activeStep.value += 1
    renderChart()
  }, 450)
}

function cancelRun() {
  if (!loading.value || cancelling.value) return
  activeRunToken.value += 1
  activeController.value?.abort()
  activeController.value = null
  loading.value = false
  cancelling.value = true
  progressText.value = '\u6b63\u5728\u505c\u6b62\u4eff\u771f...'
  errorMessage.value = '\u5df2\u53d6\u6d88\u672c\u6b21\u64cd\u4f5c\u3002'
  void request('/api/v1/simulations/cancel', { method: 'POST' })
    .then(() => {
      progressText.value = '\u4eff\u771f\u5df2\u505c\u6b62'
    })
    .catch(() => {
      progressText.value = '\u5df2\u505c\u6b62\u524d\u7aef\u8bf7\u6c42\uff0c\u540e\u7aef\u53d6\u6d88\u901a\u77e5\u5931\u8d25'
    })
    .finally(() => {
      cancelling.value = false
    })
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

function selectDatasetFile(event: Event) {
  const input = event.target as HTMLInputElement
  datasetFile.value = input.files?.[0] || null
  datasetSummary.value = null
  datasetMessage.value = datasetFile.value ? `已选择：${datasetFile.value.name}` : ''
}

async function importDataset() {
  if (!datasetFile.value || !authToken.value) {
    datasetMessage.value = '请先选择登录后可上传的 ZIP 数据集。'
    return
  }
  datasetBusy.value = true
  datasetMessage.value = '正在上传并校验数据集...'
  try {
    const body = new FormData()
    body.append('file', datasetFile.value)
    const response = await fetch('/api/v1/datasets/import', {
      method: 'POST',
      headers: { Authorization: `Bearer ${authToken.value}` },
      body
    })
    const payload = await response.json()
    if (!response.ok || payload.success === false) {
      throw new Error(payload.message || '数据集导入失败')
    }
    datasetSummary.value = payload.data as DatasetImportSummary
    datasetMessage.value = datasetSummary.value.status === 'VALIDATED'
      ? '数据集已通过校验，可作为后续场景加载来源。'
      : '数据集已保存，但校验未通过，请根据错误信息修正。'
  } catch (error) {
    datasetMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    datasetBusy.value = false
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
      void loadSavedHistory()
      void loadConversations()
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
      await request('/api/v1/simulations/cancel', { method: 'POST' })
      await request('/api/v1/auth/logout', { method: 'POST' })
    }
  } catch {
    // Clear local state even if the server is unavailable.
  }
  authToken.value = ''
  authUser.value = null
  activeRunToken.value += 1
  activeController.value?.abort()
  activeController.value = null
  loading.value = false
  cancelling.value = false
  stopPlayback()
  progressPercent.value = 0
  progressText.value = ''
  sceneLoaded.value = false
  simulation.value = null
  comparison.value = null
  savedRuns.value = []
  historyMessage.value = ''
  conversations.value = []
  activeSession.value = null
  composerText.value = ''
  chatError.value = ''
  chart?.dispose()
  chart = null
  localStorage.removeItem('fusionpilot_access_token')
  localStorage.removeItem('fusionpilot_user')
  activeView.value = 'workbench'
  window.history.pushState({}, '', '/')
  authMessage.value = '已退出登录。'
}

// The Java API serializes SchedulingResult from its record components, so the payload
// carries `assignments` but never the derived `allocatedTargetIds` list. Every result
// entering the app is normalized here so the view layer always sees one shape.
type RawScheduling = {
  policy?: string
  availableResources?: number
  assignments?: Array<{
    targetId: number
    allocated: boolean
    priorityScore?: number
    reason?: string
  }>
  allocatedTargetIds?: number[]
}

type RawStepResult = {
  timeStep: number
  trueStates?: TargetState[]
  observations?: StepResult['observations']
  fusedStates?: FusedState[]
  scheduling?: RawScheduling
  metrics?: Partial<StepResult['metrics']>
}

function normalizeScheduling(raw: RawScheduling | undefined, fallbackPolicy: string): StepResult['scheduling'] {
  const assignments = (raw?.assignments ?? []).map((item) => ({
    targetId: item.targetId,
    allocated: Boolean(item.allocated),
    priorityScore: item.priorityScore ?? 0,
    reason: item.reason ?? ''
  }))
  const provided = Array.isArray(raw?.allocatedTargetIds) ? raw.allocatedTargetIds : null
  return {
    policy: raw?.policy ?? fallbackPolicy,
    allocatedTargetIds: provided ?? assignments.filter((item) => item.allocated).map((item) => item.targetId),
    assignments
  }
}

function normalizeStep(raw: RawStepResult, fallbackPolicy: string): StepResult {
  const trueStates = raw.trueStates ?? []
  const metrics = raw.metrics ?? {}
  return {
    timeStep: raw.timeStep,
    trueStates,
    observations: raw.observations ?? [],
    fusedStates: raw.fusedStates ?? [],
    scheduling: normalizeScheduling(raw.scheduling, fallbackPolicy),
    metrics: {
      averagePositionError: metrics.averagePositionError ?? 0,
      trackingRate: metrics.trackingRate ?? 0,
      resourceUtilization: metrics.resourceUtilization ?? 0,
      allocatedTargetCount: metrics.allocatedTargetCount ?? 0,
      unservedTargetCount: metrics.unservedTargetCount ?? trueStates.length
    }
  }
}

function normalizeSimulationResult(result: SimulationResult): SimulationResult {
  if (!result) return result
  const policy = result.config?.schedulingPolicy ?? 'ROUND_ROBIN'
  return {
    ...result,
    steps: (result.steps ?? []).map((step) => normalizeStep(step as RawStepResult, policy))
  }
}

// Safe accessor for the view layer: a malformed step must never break rendering.
function allocatedIds(step: StepResult | null | undefined): number[] {
  return step?.scheduling?.allocatedTargetIds ?? []
}

function buildStepResults(base: SimulationResult, detail: SimulationRunDetail): StepResult[] {
  const timeSteps = Array.from(new Set([
    ...detail.truth.map((item) => item.timeStep),
    ...detail.observations.map((item) => item.timeStep),
    ...detail.fusedStates.map((item) => item.timeStep),
    ...detail.assignments.map((item) => item.timeStep),
    ...detail.metrics.map((item) => item.timeStep)
  ])).sort((left, right) => left - right)

  return timeSteps.map((timeStep) => normalizeStep({
    timeStep,
    trueStates: detail.truth.filter((item) => item.timeStep === timeStep),
    observations: detail.observations.filter((item) => item.timeStep === timeStep),
    fusedStates: detail.fusedStates.filter((item) => item.timeStep === timeStep),
    scheduling: {
      policy: base.config.schedulingPolicy,
      assignments: detail.assignments
        .filter((item) => item.timeStep === timeStep)
        .map((item) => ({
          targetId: item.targetId,
          allocated: item.allocated,
          priorityScore: item.priorityScore,
          reason: item.reason
        }))
    },
    metrics: detail.metrics.find((item) => item.timeStep === timeStep)
  }, base.config.schedulingPolicy))
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
    activeStep.value = Math.max(0, detailed.steps.length - 1)
    await nextTick()
    renderChart()
  } catch (error) {
    if (activeRunToken.value !== token) return
    errorMessage.value = '\u4eff\u771f\u7ed3\u679c\u5df2\u5c55\u793a\uff0c\u56de\u653e\u660e\u7ec6\u540c\u6b65\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
  }
}
async function loadDefaultConfig(): Promise<boolean> {
  loadingConfig.value = true
  errorMessage.value = ''
  try {
    config.value = await request<ExperimentConfig>('/api/v1/experiments/default')
    // No silent clamping: the panel must show exactly the configuration that will be submitted.
    sceneLoaded.value = true
    simulation.value = null
    comparison.value = null
    activeStep.value = 0
    stopPlayback()
    chart?.dispose()
    chart = null
    return true
  } catch (error) {
    errorMessage.value = '\u65e0\u6cd5\u8fde\u63a5 Java \u540e\u7aef\uff1a' + String(error)
    return false
  } finally {
    loadingConfig.value = false
  }
}

async function ensureSceneLoaded(): Promise<boolean> {
  if (sceneLoaded.value) return true
  errorMessage.value = '\u8bf7\u5148\u70b9\u51fb\u201c\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f\u201d\uff0c\u52a0\u8f7d\u6210\u529f\u540e\u518d\u8fd0\u884c\u4eff\u771f\u3002'
  progressPercent.value = 0
  progressText.value = ''
  return false
}

async function runSimulation() {
  if (!(await ensureSceneLoaded())) return

  const token = activeRunToken.value + 1
  activeRunToken.value = token
  loading.value = true
  cancelling.value = false
  errorMessage.value = ''
  comparison.value = null
  stopPlayback()
  progressPercent.value = 0
  progressText.value = '\u6b63\u5728\u521b\u5efa\u4eff\u771f\u4efb\u52a1...'

  const controller = new AbortController()
  activeController.value = controller
  const startedAt = Date.now()
  let job: SimulationJobStatus

  try {
    job = await request<SimulationJobStatus>('/api/v1/simulations/jobs', {
      method: 'POST',
      body: JSON.stringify(config.value)
    }, controller)

    const updateStatus = (status: SimulationJobStatus) => {
      progressPercent.value = status.progressPercent
      progressText.value = `${status.message} (${status.completedSteps}/${status.totalSteps})`
    }
    updateStatus(job)

    while (activeRunToken.value === token && job.status !== 'COMPLETED' && job.status !== 'CANCELLED' && job.status !== 'FAILED') {
      if (Date.now() - startedAt > 120_000) {
        throw new Error('\u4eff\u771f\u4efb\u52a1\u8d85\u8fc7 120 \u79d2\u672a\u5b8c\u6210')
      }
      await new Promise((resolve) => window.setTimeout(resolve, 200))
      job = await request<SimulationJobStatus>(
        `/api/v1/simulations/jobs/${job.jobId}`,
        undefined,
        controller
      )
      updateStatus(job)
    }

    if (activeRunToken.value !== token) return
    if (job.status === 'CANCELLED') {
      progressText.value = '\u4eff\u771f\u5df2\u505c\u6b62'
      return
    }
    if (job.status === 'FAILED' || !job.result) {
      throw new Error(job.message || '\u4eff\u771f\u4efb\u52a1\u5931\u8d25')
    }

    const result = normalizeSimulationResult(job.result)
    simulation.value = result
    activeStep.value = Math.max(0, result.steps.length - 1)
    finishProgress('\u4eff\u771f\u5df2\u5b8c\u6210')
    await nextTick()
    renderChart()
    void refreshSimulationDetailInBackground(result, token)
  } catch (error) {
    if (activeRunToken.value === token && !(error instanceof DOMException && error.name === 'AbortError')) {
      errorMessage.value = '\u4eff\u771f\u8fd0\u884c\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
      progressPercent.value = 0
      progressText.value = '\u4eff\u771f\u5931\u8d25'
    }
  } finally {
    if (activeController.value === controller) {
      activeController.value = null
    }
    if (activeRunToken.value === token) {
      loading.value = false
    }
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
  progressPercent.value = 0
  progressText.value = '\u6b63\u5728\u8ba1\u7b97\u4e24\u79cd\u8c03\u5ea6\u7b56\u7565...'
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
  const priorityResult = normalizeSimulationResult(result.priority)
  simulation.value = priorityResult
  activeStep.value = 0
  finishProgress('\u7b56\u7565\u5bf9\u6bd4\u5b8c\u6210')
  await nextTick()
  try {
    renderChart()
    void refreshSimulationDetailInBackground(priorityResult, token)
  } catch (error) {
    errorMessage.value = '\u5bf9\u6bd4\u5df2\u5b8c\u6210\uff0c\u4f46\u8f68\u8ff9\u56fe\u6e32\u67d3\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
  }
}


// --- Multi-turn conversation ----------------------------------------------------------------
// The agent service owns the transcript. This page only mirrors the session it last received,
// so what is on screen is what the loop actually recorded rather than a client-side guess.
const conversations = ref<AgentConversationSummary[]>([])
const activeSession = ref<AgentConversation | null>(null)
const sessionBusy = ref(false)
const sessionsLoading = ref(false)
const composerText = ref('')
const chatError = ref('')
const autoApproveTools = ref(false)
const transcriptEl = ref<HTMLElement | null>(null)
const liveStage = ref<string | null>(null)
// Token deltas streamed from the model, rendered inline until the full assistant message lands.
const streamingText = ref('')

// --- Bring-your-own model token -------------------------------------------------------------
// The token is held in memory by default and only sent as the `X-Model-Api-Key` header. It is
// never put in a request body, so the agent service cannot persist it with a session.
const AGENT_KEY_STORAGE = 'fusionpilot_agent_api_key'
const AGENT_REMEMBER_STORAGE = 'fusionpilot_agent_remember'

const agentApiKey = ref('')
const agentApiBase = ref('')
const agentRememberKey = ref(false)
const agentKeyVisible = ref(false)
const agentKeyTesting = ref(false)
const agentKeyResult = ref<AgentConnectionTest | null>(null)
const agentKeyError = ref('')

const agentHasKey = computed(() => agentApiKey.value.trim().length > 0)
const agentUsesModel = computed(() => (
  selectedAgentProvider.value !== 'rule'
  && (agentHasKey.value || Boolean(selectedProviderInfo.value?.serverConfigured))
))

function persistAgentKey() {
  if (agentRememberKey.value && agentApiKey.value.trim()) {
    localStorage.setItem(AGENT_KEY_STORAGE, agentApiKey.value.trim())
    localStorage.setItem(AGENT_REMEMBER_STORAGE, 'true')
  } else {
    localStorage.removeItem(AGENT_KEY_STORAGE)
    localStorage.setItem(AGENT_REMEMBER_STORAGE, 'false')
  }
}

function loadStoredAgentKey() {
  agentRememberKey.value = localStorage.getItem(AGENT_REMEMBER_STORAGE) === 'true'
  if (agentRememberKey.value) {
    agentApiKey.value = localStorage.getItem(AGENT_KEY_STORAGE) ?? ''
  }
}

function forgetAgentKey() {
  agentApiKey.value = ''
  agentRememberKey.value = false
  agentKeyResult.value = null
  agentKeyError.value = ''
  localStorage.removeItem(AGENT_KEY_STORAGE)
  localStorage.setItem(AGENT_REMEMBER_STORAGE, 'false')
}

async function testAgentModel() {
  if (selectedAgentProvider.value === 'rule') {
    agentKeyError.value = '\u5f53\u524d\u662f\u672c\u5730\u89c4\u5219\u6a21\u5f0f\uff0c\u4e0d\u9700\u8981\u4e5f\u4e0d\u4f1a\u8c03\u7528\u5916\u90e8\u6a21\u578b\u3002'
    return
  }
  agentKeyTesting.value = true
  agentKeyResult.value = null
  agentKeyError.value = ''
  try {
    agentKeyResult.value = await requestAgent<AgentConnectionTest>('/api/v1/agent/models/test', {
      method: 'POST',
      body: JSON.stringify({
        provider: selectedAgentProvider.value,
        model: selectedAgentModel.value.trim() || null,
        api_base_url: agentApiBase.value.trim() || null
      })
    })
  } catch (error) {
    agentKeyError.value = '\u8fde\u63a5\u6d4b\u8bd5\u5931\u8d25\uff1a' + (error instanceof Error ? error.message : String(error))
  } finally {
    agentKeyTesting.value = false
  }
}

// A model call can legitimately take tens of seconds, so this budget must exceed the agent
// service's own provider timeout (MODEL_TIMEOUT_SECONDS) rather than aborting a healthy request.
const AGENT_REQUEST_TIMEOUT_MS = 60000

async function requestAgent<T>(
  url: string,
  options?: RequestInit,
  timeoutMs: number = AGENT_REQUEST_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...(authToken.value ? { Authorization: `Bearer ${authToken.value}` } : {}),
        // The user's own model token travels as a header, never in the JSON body, so it can
        // never be echoed back or stored inside an agent session snapshot.
        ...(agentApiKey.value.trim() ? { 'X-Model-Api-Key': agentApiKey.value.trim() } : {}),
        ...(agentApiBase.value.trim() ? { 'X-Model-Api-Base': agentApiBase.value.trim() } : {})
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
      throw new Error('Agent request timed out. A slow model may still be answering.')
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}

function navigateTo(view: AgentView) {
  if (activeView.value === view) return
  activeView.value = view
  const path = view === 'agent' ? '/agent' : '/'
  window.history.replaceState({}, '', path)
  window.scrollTo({ top: 0, behavior: 'auto' })
  if (view === 'agent') {
    void loadConversations()
    void scrollTranscriptToEnd()
  }
}

function handlePopState() {
  activeView.value = window.location.pathname === '/agent' ? 'agent' : 'workbench'
}

function handleAgentProviderChange() {
  closeModelDropdown()
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
  agentKeyResult.value = null
  agentKeyError.value = ''
}

const AGENT_TOOL_LABELS: Record<string, string> = {
  get_experiment_config: '读取当前配置',
  update_experiment_config: '修改实验配置',
  validate_experiment: '校验仿真配置',
  run_simulation: '执行雷达仿真',
  calculate_metrics: '提取指标',
  compare_scheduling_policies: '比较资源调度'
}

function agentToolLabel(name: string) {
  return AGENT_TOOL_LABELS[name] ?? name
}

const canSendMessage = computed(() => (
  Boolean(activeSession.value) && composerText.value.trim().length > 0 && !sessionBusy.value
))

/** Tool results are stored as the JSON the model saw, so the reason is pulled back out of it. */
function toolFailureText(message: AgentChatMessage) {
  try {
    const parsed = JSON.parse(message.content) as { error?: unknown }
    return typeof parsed.error === 'string' ? parsed.error : message.content
  } catch {
    return message.content
  }
}

function shortClock(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

async function scrollTranscriptToEnd() {
  await nextTick()
  const element = transcriptEl.value
  if (element) {
    element.scrollTop = element.scrollHeight
  }
}

async function loadConversations() {
  sessionsLoading.value = true
  try {
    conversations.value = await requestAgent<AgentConversationSummary[]>('/api/v1/agent/conversations')
  } catch (error) {
    chatError.value = '\u65e0\u6cd5\u8bfb\u53d6\u5386\u53f2\u5bf9\u8bdd\uff1a' + String(error)
  } finally {
    sessionsLoading.value = false
  }
}

const agentRequestShape = () => ({
  model_provider: selectedAgentProvider.value,
  model_name: selectedAgentProvider.value === 'rule' ? null : selectedAgentModel.value.trim() || null,
  model_api_base_url: agentApiBase.value.trim() || null
})

async function createConversation() {
  sessionBusy.value = true
  chatError.value = ''
  try {
    activeSession.value = await requestAgent<AgentConversation>('/api/v1/agent/conversations', {
      method: 'POST',
      body: JSON.stringify({
        auto_approve: autoApproveTools.value,
        model_provider: selectedAgentProvider.value,
        model_name: selectedAgentProvider.value === 'rule' ? null : selectedAgentModel.value.trim() || null
      })
    })
    await loadConversations()
    await scrollTranscriptToEnd()
  } catch (error) {
    chatError.value = '\u65e0\u6cd5\u521b\u5efa\u5bf9\u8bdd\uff1a' + String(error)
  } finally {
    sessionBusy.value = false
  }
}

async function openConversation(sessionId: string) {
  if (sessionBusy.value) return
  sessionBusy.value = true
  chatError.value = ''
  try {
    activeSession.value = await requestAgent<AgentConversation>(
      `/api/v1/agent/conversations/${sessionId}`,
      undefined,
      40000
    )
    await scrollTranscriptToEnd()
  } catch (error) {
    chatError.value = '\u65e0\u6cd5\u8bfb\u53d6\u5bf9\u8bdd\uff1a' + String(error)
  } finally {
    sessionBusy.value = false
  }
}

async function removeConversation(sessionId: string) {
  if (sessionBusy.value) return
  chatError.value = ''
  try {
    await requestAgent(`/api/v1/agent/conversations/${sessionId}`, { method: 'DELETE' })
    if (activeSession.value?.session_id === sessionId) {
      activeSession.value = null
    }
    await loadConversations()
  } catch (error) {
    chatError.value = '\u5220\u9664\u5931\u8d25\uff1a' + String(error)
  }
}

const agentHeaders = () => ({
  'Content-Type': 'application/json',
  ...(authToken.value ? { Authorization: `Bearer ${authToken.value}` } : {}),
  ...(agentApiKey.value.trim() ? { 'X-Model-Api-Key': agentApiKey.value.trim() } : {}),
  ...(agentApiBase.value.trim() ? { 'X-Model-Api-Base': agentApiBase.value.trim() } : {})
})

function describeProgress(eventType: string, payload: Record<string, unknown>): string | null {
  switch (eventType) {
    case 'assistant_message': return '模型正在组织下一步…'
    case 'understanding_query': return '正在理解你的问题…'
    case 'plan_created': return '已设计多步实验计划'
    case 'knowledge_retrieved': return payload.grounded === false ? '平台资料中没有对应小节' : '正在查阅平台资料…'
    case 'analysis_ready': return '正在解读运行结果…'
    case 'tool_called': return `正在执行「${agentToolLabel(String(payload.tool_name ?? ''))}」…`
    case 'tool_failed': return `「${agentToolLabel(String(payload.tool_name ?? ''))}」参数有误`
    case 'tool_result': return payload.ok === false ? `「${agentToolLabel(String(payload.tool_name ?? ''))}」失败` : null
    case 'confirmation_requested': return '等待你的确认'
    case 'clarification_requested': return '需要你补充一点信息'
    case 'intent_classified': return null
    case 'confirmation_received': return '已批准，继续执行…'
    case 'confirmation_declined': return '已拒绝'
    case 'confirmation_cancelled': return '已放弃上一次待确认操作'
    case 'turn_step_limit_reached': return '已达本回合步数上限'
    case 'plan_created': return '规则模式：已生成一步计划'
    default: return null
  }
}

function applyStreamEvent(eventName: string, data: unknown) {
  if (!activeSession.value) return
  if (eventName === 'message') {
    activeSession.value.messages.push(data as AgentChatMessage)
    streamingText.value = ''
    void scrollTranscriptToEnd()
  } else if (eventName === 'progress') {
    const item = data as { event_type: string; payload: Record<string, unknown> }
    if (item.event_type === 'token') {
      // Live prose: append the delta and keep the view pinned to the bottom.
      streamingText.value += String(item.payload.text ?? '')
      void scrollTranscriptToEnd()
      return
    }
    liveStage.value = describeProgress(item.event_type, item.payload)
    if (item.event_type === 'confirmation_requested') {
      // The authoritative pending object arrives with the final `session` frame; this only makes
      // the approval card show up immediately instead of a beat later.
      activeSession.value.status = 'AWAITING_CONFIRMATION'
    }
  } else if (eventName === 'session') {
    activeSession.value = data as AgentConversation
    streamingText.value = ''
    liveStage.value = null
    void scrollTranscriptToEnd()
  } else if (eventName === 'error') {
    const error = data as { message?: string }
    chatError.value = String(error?.message ?? 'Agent 执行中断')
    streamingText.value = ''
    liveStage.value = null
  }
}

function parseSseFrame(frame: string): { event: string; data: unknown } | null {
  let event = 'message'
  let data: unknown = null
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      const raw = line.slice(5).trim()
      try {
        data = raw ? JSON.parse(raw) : null
      } catch {
        data = raw
      }
    }
  }
  return data === null ? null : { event, data }
}

async function streamAgentTurn(
  path: string,
  body: Record<string, unknown>,
  onEvent: (eventName: string, data: unknown) => void
): Promise<void> {
  const response = await fetch(path, { method: 'POST', headers: agentHeaders(), body: JSON.stringify(body) })
  if (!response.ok) {
    let message = `Agent request failed (${response.status})`
    try {
      const payload = await response.json()
      const detail = payload.detail
      message = typeof detail === 'object' && detail ? detail.message : String(detail || message)
    } catch {
      // keep the status-based message
    }
    throw new Error(message)
  }
  if (!response.body) throw new Error('Agent 流式响应没有内容')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let index = buffer.indexOf('\n\n')
      while (index >= 0) {
        const parsed = parseSseFrame(buffer.slice(0, index))
        buffer = buffer.slice(index + 2)
        if (parsed) onEvent(parsed.event, parsed.data)
        index = buffer.indexOf('\n\n')
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/** Run a turn over SSE; returns whether the stream reached a resolution (session or error). */
async function runStreamedTurn(path: string, body: Record<string, unknown>): Promise<boolean> {
  let resolved = false
  const handler = (eventName: string, data: unknown) => {
    if (eventName === 'session' || eventName === 'error') resolved = true
    applyStreamEvent(eventName, data)
  }
  await streamAgentTurn(path, body, handler)
  return resolved
}

async function sendChatMessage() {
  if (!canSendMessage.value || !activeSession.value) return
  const sessionId = activeSession.value.session_id
  const text = composerText.value.trim()
  sessionBusy.value = true
  chatError.value = ''
  liveStage.value = '模型正在思考…'
  composerText.value = ''
  const body = { message: text, auto_approve: autoApproveTools.value, ...agentRequestShape() }
  try {
    const resolved = await runStreamedTurn(
      `/api/v1/agent/conversations/${sessionId}/messages/stream`,
      body
    )
    // Refreshing the list is not part of the turn and must not hold the busy flag.
    void loadConversations()
    if (!resolved) {
      // The stream never reached a resolution, usually a transport failure. The turn keeps running
      // on the server, so re-read the authoritative state instead of re-running it.
      activeSession.value = await requestAgent<AgentConversation>(
        `/api/v1/agent/conversations/${sessionId}`,
        undefined,
        40000
      )
    }
  } catch (error) {
    chatError.value = error instanceof Error ? error.message : String(error)
  } finally {
    sessionBusy.value = false
    liveStage.value = null
    await scrollTranscriptToEnd()
  }
}

async function decidePendingTool(approve: boolean) {
  if (!activeSession.value?.pending || sessionBusy.value) return
  const sessionId = activeSession.value.session_id
  sessionBusy.value = true
  chatError.value = ''
  liveStage.value = approve ? '已批准，继续执行…' : '已拒绝'
  const body = { approve, ...agentRequestShape() }
  try {
    const resolved = await runStreamedTurn(
      `/api/v1/agent/conversations/${sessionId}/decision/stream`,
      body
    )
    void loadConversations()
    if (!resolved) {
      activeSession.value = await requestAgent<AgentConversation>(
        `/api/v1/agent/conversations/${sessionId}`,
        undefined,
        40000
      )
    }
  } catch (error) {
    chatError.value = error instanceof Error ? error.message : String(error)
  } finally {
    sessionBusy.value = false
    liveStage.value = null
    await scrollTranscriptToEnd()
  }
}

/** Open a run the agent produced in the workbench, where the trajectory chart lives. */
async function openRunInWorkbench(runId: string) {
  await loadSavedRun({
    runId,
    scenarioName: '\u0041\u0067\u0065\u006e\u0074 \u8fd0\u884c'
  } as unknown as SavedRunSummary)
  navigateTo('workbench')
}

function renderChart() {
  const element = chartElement.value
  const result = simulation.value
  if (!element || !result || !result.steps.length) return
  // Reuse the existing instance. Re-initializing on every frame used to leak
  // instances and make the chart flicker during playback.
  if (!chart || chart.getDom() !== element) {
    chart?.dispose()
    chart = echarts.init(element)
  }

  const steps = result.steps.slice(0, activeStep.value + 1)
  const colors = ['#38bdf8', '#a78bfa', '#fbbf24']
  // Derive the tracked targets from the data instead of the form state, so the
  // chart stays correct after a scenario or comparison result is swapped in.
  const targetIds = Array.from(new Set(
    steps.flatMap((step) => [
      ...step.trueStates.map((item) => item.targetId),
      ...step.fusedStates.map((item) => item.targetId)
    ])
  )).sort((left, right) => left - right)

  const findPoint = (
    states: Array<{ targetId: number; x: number; y: number }>,
    targetId: number
  ): [number, number] | null => {
    const state = states.find((item) => item.targetId === targetId)
    return state ? [Number(state.x.toFixed(4)), Number(state.y.toFixed(4))] : null
  }

  const series = []
  for (const targetId of targetIds) {
    const color = colors[(targetId - 1) % colors.length] ?? '#38bdf8'
    series.push(
      {
        name: `T${targetId} \u771f\u5b9e`,
        type: 'line',
        data: steps.map((step) => findPoint(step.trueStates, targetId)),
        symbol: 'none',
        connectNulls: false,
        lineStyle: { width: 2, color },
        itemStyle: { color }
      },
      {
        name: `T${targetId} \u878d\u5408`,
        type: 'line',
        data: steps.map((step) => findPoint(step.fusedStates, targetId)),
        symbol: 'circle',
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { type: 'dashed', color },
        itemStyle: { color }
      }
    )
  }

  chart.setOption({
    backgroundColor: 'transparent',
    animation: steps.length < 200,
    tooltip: { trigger: 'axis' },
    legend: { top: 4, textStyle: { color: '#9fb1c8' } },
    grid: { left: 52, right: 22, top: 46, bottom: 38 },
    xAxis: { type: 'value', name: 'X', scale: true, axisLabel: { color: '#71839b' }, splitLine: { lineStyle: { color: '#203047' } } },
    yAxis: { type: 'value', name: 'Y', scale: true, axisLabel: { color: '#71839b' }, splitLine: { lineStyle: { color: '#203047' } } },
    series
  }, { notMerge: true })
}

function resizeChart() {
  chart?.resize()
}

async function scheduleChartRender() {
  await nextTick()
  if (chartRenderFrame !== undefined) {
    window.cancelAnimationFrame(chartRenderFrame)
  }
  chartRenderFrame = window.requestAnimationFrame(() => {
    chartRenderFrame = undefined
    renderChart()
  })
}

watch([simulation, activeStep, activeView], () => {
  if (activeView.value === 'workbench' && simulation.value) {
    void scheduleChartRender()
  }
}, { flush: 'post' })

onMounted(async () => {
  window.addEventListener('popstate', handlePopState)
  window.addEventListener('resize', resizeChart)
  document.addEventListener('click', onDocumentClick)
  loadStoredAgentKey()
  const storedToken = localStorage.getItem('fusionpilot_access_token')
  if (storedToken) {
    try {
      authToken.value = storedToken
      authUser.value = await request<AuthUser>('/api/v1/auth/me')
      localStorage.setItem('fusionpilot_user', JSON.stringify(authUser.value))
      void loadAgentModelStatus()
      void loadSavedHistory()
      if (activeView.value === 'agent') {
        void loadConversations()
      }
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
  document.removeEventListener('click', onDocumentClick)
  stopPlayback()
  if (chartRenderFrame !== undefined) {
    window.cancelAnimationFrame(chartRenderFrame)
  }
  activeController.value?.abort()
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
            <button class="ghost-button" :disabled="loadingConfig || loading" @click="loadDefaultConfig">{{ loadingConfig ? '\u52a0\u8f7d\u4e2d...' : '\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f' }}</button>
          </div>

          <div class="scene-state" :class="{ ready: sceneLoaded }">
            <span>{{ sceneLoaded ? '\u573a\u666f\u5df2\u52a0\u8f7d' : '\u8bf7\u5148\u52a0\u8f7d\u573a\u666f' }}</span>
          </div>

          <div class="dataset-import">
            <div class="subsection-title">用户数据集</div>
            <small>上传包含 manifest.json、observations.csv 的 ZIP；truth.csv 可用于误差评估。</small>
            <input type="file" accept=".zip" @change="selectDatasetFile" />
            <button class="ghost-button" :disabled="datasetBusy || !datasetFile" @click="importDataset">
              {{ datasetBusy ? '校验中...' : '上传并校验数据集' }}
            </button>
            <p v-if="datasetMessage" class="dataset-message">{{ datasetMessage }}</p>
            <div v-if="datasetSummary" class="dataset-summary">
              <strong>{{ datasetSummary.status }}</strong>
              <span>观测 {{ datasetSummary.observationRows }} 行 / 真值 {{ datasetSummary.truthRows }} 行</span>
              <span v-for="warning in datasetSummary.warnings" :key="warning">{{ warning }}</span>
              <span v-for="error in datasetSummary.errors" :key="error" class="dataset-error">{{ error }}</span>
            </div>
          </div>

          <label class="field"><span>场景名称</span><input v-model="config.scenarioName" maxlength="80" /></label>
          <div class="field-grid">
            <label class="field"><span>目标数量</span><input v-model.number="config.targetCount" type="number" min="1" max="50" step="1" /></label>
            <label class="field"><span>资源数量</span><input v-model.number="config.availableResources" type="number" min="1" max="50" step="1" /></label>
            <label class="field"><span>时间步数</span><input v-model.number="config.simulationSteps" type="number" min="1" max="10000" step="1" /></label>
            <label class="field"><span>时间步长 (秒)</span><input v-model.number="config.timeStepSeconds" type="number" min="0.01" step="0.1" /></label>
          </div>

          <label class="field"><span>随机种子</span><input v-model.number="config.randomSeed" type="number" step="1" /></label>

          <label class="field">
            <span>调度策略</span>
            <select v-model="config.schedulingPolicy">
              <option value="ROUND_ROBIN">轮询调度</option>
              <option value="PRIORITY">优先级调度</option>
            </select>
          </label>

          <label class="field">
            <span>融合方法</span>
            <select v-model="config.fusionMethod">
              <option v-for="option in fusionMethodOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>

          <div class="source-list">
            <div class="subsection-title">
              <span>观测源</span>
              <button
                type="button"
                class="ghost-button compact-button"
                :disabled="loading"
                title="恢复为后端默认的雷达 / 光电红外 / 先验参数"
                @click="resetObservationSources"
              >恢复默认</button>
            </div>
            <div v-for="source in config.observationSources" :key="source.type" class="source-card">
              <div class="source-head">
                <strong>{{ sourceLabel(source.type) }}</strong>
                <span class="source-confidence">{{ Math.round(source.confidence * 100) }}%</span>
              </div>
              <label class="slider-field">
                <span>噪声 σ<em>{{ oneDecimal(source.noiseStdDev) }}</em></span>
                <input v-model.number="source.noiseStdDev" type="range" min="0" max="30" step="0.5" />
              </label>
              <label class="slider-field">
                <span>缺失率<em>{{ Math.round(source.missingRate * 100) }}%</em></span>
                <input v-model.number="source.missingRate" type="range" min="0" max="1" step="0.01" />
              </label>
              <label class="slider-field">
                <span>延迟<em>{{ source.delaySteps }} 步</em></span>
                <input v-model.number="source.delaySteps" type="range" min="0" max="10" step="1" />
              </label>
              <label class="slider-field">
                <span>置信度<em>{{ Math.round(source.confidence * 100) }}%</em></span>
                <input v-model.number="source.confidence" type="range" min="0.1" max="1" step="0.01" />
              </label>
            </div>
          </div>

          <div v-if="configIssues.length" class="config-issues">
            <span v-for="issue in configIssues" :key="issue">{{ issue }}</span>
          </div>
          <div v-else-if="configHints.length" class="config-hints">
            <span v-for="hint in configHints" :key="hint">{{ hint }}</span>
          </div>

          <details class="param-help">
            <summary>参数说明</summary>
            <dl>
              <div><dt>目标数量</dt><dd>生成 n 个匀速直线目标，初值 (100n, 60n)，速度 (2 + 0.5n, 1 + 0.25n) / 秒</dd></div>
              <div><dt>资源数量</dt><dd>每步最多可服务的槽位数；超出的目标计入未服务，影响平均等待</dd></div>
              <div><dt>时间步数</dt><dd>仿真总步数，步数 × 步长 = 场景时长</dd></div>
              <div><dt>时间步长</dt><dd>秒 / 步，同时决定目标每步位移与预测外推距离</dd></div>
              <div><dt>随机种子</dt><dd>与步数组合决定全部噪声与丢帧；相同种子结果完全可复现</dd></div>
              <div><dt>调度策略</dt><dd>轮询按时间步轮转起点；优先级按不确定性、预测态与跟踪质量打分</dd></div>
              <div><dt>融合方法</dt><dd>五种算法消费同一批观测，可直接横向对比</dd></div>
              <div><dt>观测源 · 噪声 σ</dt><dd>位置高斯噪声标准差，x、y 各自独立叠加</dd></div>
              <div><dt>观测源 · 缺失率</dt><dd>每步按该概率直接丢帧，不产生观测</dd></div>
              <div><dt>观测源 · 延迟</dt><dd>报告的是 delay 步之前的目标位置，模拟传感器数据滞后</dd></div>
              <div><dt>观测源 · 置信度</dt><dd>融合权重；先验源在计算时会额外乘以 0.8</dd></div>
            </dl>
          </details>

          <div v-if="loading || cancelling || progressText" class="run-progress">
            <div class="progress-heading">
              <span>{{ progressText }}</span>
              <strong>{{ progressPercent }}%</strong>
            </div>
            <div class="progress-track"><span :style="{ width: `${progressPercent}%` }"></span></div>
            <button type="button" v-if="loading && !cancelling" class="cancel-button" @click.stop.prevent="cancelRun">&#20572;&#27490;&#31561;&#24453;</button>
          </div>

          <div class="action-stack">
            <button class="primary-button" :disabled="!canRun" @click="runSimulation"><span class="button-icon">&gt;</span>{{ loading ? '\u8fd0\u884c\u4e2d...' : cancelling ? '\u505c\u6b62\u4e2d...' : '\u8fd0\u884c\u4eff\u771f' }}</button>
            <button class="secondary-button" :disabled="!canRun" @click="comparePolicies"><span class="button-icon">&lt;&gt;</span>&#23545;&#27604;&#35843;&#24230;&#31574;&#30053;</button>
            <button
              class="secondary-button save-button"
              type="button"
              :disabled="!simulation || currentRunSaved"
              :title="currentRunSaved ? '这次结果已经在历史记录里了' : '把这次结果存入历史记录'"
              @click="saveCurrentRun"
            ><span class="button-icon">&#43;</span>{{ currentRunSaved ? '\u5df2\u4fdd\u5b58' : '\u4fdd\u5b58\u7ed3\u679c' }}</button>
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
              <div class="panel-heading compact"><div><span class="panel-kicker">03 / &#22238;&#25918;</span><h2>&#26102;&#38388;&#27493;&#26597;&#30475;</h2></div><div class="step-controls"><button v-if="simulation" class="ghost-button compact-button" type="button" @click="togglePlayback">{{ playbackPlaying ? '&#26242;&#20572;' : '&#25773;&#25918;' }}</button><span class="step-counter">{{ currentStep ? `${currentStep.timeStep + 1} / ${simulation?.steps.length}` : '--' }}</span></div></div>
              <input v-if="simulation" v-model.number="activeStep" class="range" type="range" min="0" :max="Math.max(0, simulation.steps.length - 1)" @input="renderChart" />
              <div v-if="currentStep" class="step-details">
                <div class="detail-chip"><span class="detail-label">&#26377;&#25928;&#35266;&#27979;</span><strong>{{ currentStep.observations.filter((item) => item.available).length }}</strong></div>
                <div class="detail-chip"><span class="detail-label">&#24050;&#20998;&#37197;&#30446;&#26631;</span><strong>{{ allocatedIds(currentStep).join(', ') || '\u65e0' }}</strong></div>
                <div class="detail-chip"><span class="detail-label">&#24403;&#27493;&#35823;&#24046;</span><strong>{{ formatNumber(currentStep.metrics.averagePositionError) }}</strong></div>
              </div>
            </div>

            <div class="panel schedule-panel">
              <div class="panel-heading compact"><div><span class="panel-kicker">04 / &#36164;&#28304;&#26085;&#24535;</span><h2>&#26368;&#36817;&#20998;&#37197;</h2></div><span class="policy-tag">{{ simulation?.config.schedulingPolicy ?? '--' }}</span></div>
              <div v-if="visibleSteps.length" class="schedule-list">
                <div v-for="step in visibleSteps" :key="step.timeStep" class="schedule-row"><span class="time-index">T{{ step.timeStep }}</span><div class="allocation-bar"><span v-for="targetId in resourceSlots" :key="targetId" :class="{ active: allocatedIds(step).includes(targetId) }"></span></div><span class="allocation-count">{{ allocatedIds(step).length }}/{{ simulation?.config.availableResources ?? config.availableResources }}</span></div>
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

          <div class="panel history-panel">
            <div class="panel-heading compact">
              <div>
                <span class="panel-kicker">06 / 历史</span>
                <h2>已保存的运行</h2>
              </div>
              <div class="history-controls">
                <span class="policy-tag">{{ savedRuns.length }} / {{ HISTORY_LIMIT }}</span>
                <button class="ghost-button compact-button" type="button" :disabled="historyLoading" @click="loadSavedHistory">
                  {{ historyLoading ? '刷新中...' : '刷新' }}
                </button>
              </div>
            </div>

            <p class="history-note">
              只有点击「保存结果」的运行才会进入这里，每个账号最多保留 {{ HISTORY_LIMIT }} 条；超出时最旧的一条会被移除。
            </p>

            <div v-if="savedRuns.length" class="history-list">
              <div
                v-for="entry in savedRuns"
                :key="entry.runId"
                class="history-row"
                :class="{ current: simulation?.runId === entry.runId }"
              >
                <div class="history-meta">
                  <strong>{{ entry.scenarioName }}</strong>
                  <small>
                    {{ entry.targetCount }} 目标 · {{ entry.simulationSteps }} 步 ·
                    {{ fusionMethodLabel(entry.fusionMethod) }} ·
                    存入 {{ formatTimestamp(entry.savedAt) }}
                  </small>
                </div>
                <div class="history-metrics">
                  <span>误差 <strong>{{ formatNumber(entry.averagePositionError) }}</strong></span>
                  <span>跟踪 <strong>{{ formatNumber(entry.trackingRate * 100, 1) }}%</strong></span>
                </div>
                <div class="history-actions">
                  <button class="ghost-button compact-button" type="button" @click="loadSavedRun(entry)">载入</button>
                  <button class="ghost-button compact-button danger" type="button" @click="deleteSavedRun(entry)">移除</button>
                </div>
              </div>
            </div>
            <div v-else class="muted-empty">
              {{ authUser ? '还没有保存过运行结果。跑一次仿真后点击左侧的「保存结果」。' : '登录后可以保存并回看历史结果。' }}
            </div>

            <p v-if="historyMessage" class="history-note strong">{{ historyMessage }}</p>
          </div>
        </section>
      </section>
      <section v-if="authUser && activeView === 'agent'" class="agent-page">
        <div class="agent-page-hero">
          <div>
            <p class="eyebrow">FUSIONPILOT / RESEARCH COPILOT</p>
            <h1>雷达与电子对抗协同助手</h1>
            <p class="lede">
              多轮对话式协同：Agent 自己读取配置、修改参数、调用仿真并解读指标。仿真事实永远来自 Java 核心，
              需要花费资源的工具会先向你申请确认。
            </p>
          </div>
          <div class="agent-model-status">
            <span class="panel-kicker">ACTIVE MODEL</span>
            <strong>{{ selectedProviderLabel }}</strong>
            <span>{{ selectedModelName }}</span>
            <em>{{ selectedAgentProvider === 'rule' ? 'LOCAL RULES' : agentUsesModel ? 'MODEL ACTIVE' : 'NO TOKEN' }}</em>
          </div>
        </div>

        <div class="agent-model-bar">
          <label class="field model-bar-field">
            <span>提供商</span>
            <select v-model="selectedAgentProvider" @change="handleAgentProviderChange">
              <option value="rule">本地规则</option>
              <option v-for="provider in agentModelStatus?.providers ?? []" :key="provider.provider" :value="provider.provider">{{ provider.label }}</option>
            </select>
          </label>
          <label class="field model-bar-field model-bar-model">
            <span>模型 <em v-if="selectedModelIsFree" class="free-badge">免费</em></span>
            <div class="model-select">
              <button
                type="button"
                class="model-select-trigger"
                :disabled="selectedAgentProvider === 'rule'"
                @click="toggleModelDropdown"
              >
                <span class="model-select-value">{{ selectedModelName }}</span>
                <span class="model-select-caret" :class="{ open: modelDropdownOpen }">▾</span>
              </button>
              <div v-if="modelDropdownOpen" class="model-select-menu">
                <input
                  class="model-select-search"
                  v-model="modelSearch"
                  placeholder="搜索，或直接输入任意模型名"
                  autocomplete="off"
                  spellcheck="false"
                  @keydown.enter.prevent="pickModel(modelSearch.trim())"
                />
                <div class="model-select-list">
                  <button
                    v-for="model in filteredModelOptions"
                    :key="model"
                    type="button"
                    class="model-option"
                    :class="{ free: isFreeModel(model), active: model === selectedAgentModel }"
                    @click="pickModel(model)"
                  >
                    <span class="model-option-name">{{ model }}</span>
                    <em v-if="isFreeModel(model)" class="model-option-free">免费</em>
                  </button>
                  <button
                    v-if="modelSearch.trim() && !selectedModelOptions.includes(modelSearch.trim())"
                    type="button"
                    class="model-option model-option-custom"
                    @click="pickModel(modelSearch.trim())"
                  >
                    <span class="model-option-name">使用自定义模型「{{ modelSearch.trim() }}」</span>
                  </button>
                  <div v-if="!filteredModelOptions.length" class="model-select-empty">
                    {{ modelSearch.trim() ? '无匹配，回车使用上面的自定义项' : '暂无可选模型' }}
                  </div>
                </div>
              </div>
            </div>
          </label>
          <label v-if="selectedAgentProvider !== 'rule'" class="field model-bar-field model-bar-key">
            <span>你的 API 令牌</span>
            <div class="password-shell">
              <input
                v-model="agentApiKey"
                :type="agentKeyVisible ? 'text' : 'password'"
                placeholder="粘贴你自己的模型 API Key"
                autocomplete="off"
                spellcheck="false"
                @change="persistAgentKey"
              />
              <button
                type="button"
                class="password-toggle"
                :class="{ 'is-visible': agentKeyVisible }"
                :title="agentKeyVisible ? '隐藏令牌' : '显示令牌'"
                :aria-label="agentKeyVisible ? '隐藏令牌' : '显示令牌'"
                @click="agentKeyVisible = !agentKeyVisible"
              ></button>
            </div>
          </label>
          <div class="model-bar-actions">
            <button v-if="selectedAgentProvider !== 'rule'" class="ghost-button" :disabled="agentKeyTesting" @click="testAgentModel">
              {{ agentKeyTesting ? '测试中…' : '测试连接' }}
            </button>
            <details class="model-bar-advanced">
              <summary class="ghost-button">高级</summary>
              <div class="model-bar-advanced-body">
                <label class="field">
                  <span>自定义接口地址（可选）</span>
                  <input v-model="agentApiBase" placeholder="留空用官方地址；可填自建或代理网关" autocomplete="off" spellcheck="false" />
                </label>
                <div class="agent-key-actions">
                  <button class="ghost-button" type="button" :disabled="!agentHasKey && !agentRememberKey" @click="forgetAgentKey">清除令牌</button>
                  <label class="remember-key"><input v-model="agentRememberKey" type="checkbox" @change="persistAgentKey" />记住在这台浏览器</label>
                </div>
              </div>
            </details>
          </div>
          <label class="remember-key model-bar-auto">
            <input v-model="autoApproveTools" type="checkbox" />自动批准执行类工具
          </label>
          <p v-if="agentKeyResult" class="agent-message model-bar-note">连接成功：{{ agentKeyResult.label }} / {{ agentKeyResult.model }}</p>
          <p v-if="agentKeyError" class="agent-error model-bar-note">{{ agentKeyError }}</p>
          <p v-else-if="selectedAgentProvider !== 'rule' && !agentUsesModel" class="agent-hint model-bar-note">
            没有令牌时，多轮对话需要你自己的模型令牌，否则只会按规则执行一步。
          </p>
          <p v-else-if="selectedAgentProvider === 'rule'" class="agent-key-note model-bar-note">
            本地规则模式不调用外部模型；需要真正的多轮协同，请选择模型提供商并粘贴你自己的令牌。
          </p>
        </div>

        <div class="agent-chat-grid">
          <aside class="panel conversation-panel">
            <div class="panel-heading compact">
              <div><span class="panel-kicker">00 / SESSIONS</span><h2>历史对话</h2></div>
              <span class="policy-tag">{{ conversations.length }}</span>
            </div>
            <button class="primary-button conversation-new" :disabled="sessionBusy" @click="createConversation">新对话</button>
            <div v-if="sessionsLoading" class="muted-empty">正在读取…</div>
            <div v-else-if="!conversations.length" class="muted-empty">还没有对话，创建一个开始。</div>
            <ul v-else class="conversation-list">
              <li
                v-for="item in conversations"
                :key="item.session_id"
                :class="{ active: item.session_id === activeSession?.session_id }"
              >
                <button class="conversation-open" @click="openConversation(item.session_id)">
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.working_summary || '默认配置' }}</small>
                  <em>{{ item.message_count }} 条 · {{ item.tool_call_count }} 次工具调用</em>
                </button>
                <button class="ghost-button conversation-remove" @click="removeConversation(item.session_id)">移除</button>
              </li>
            </ul>
          </aside>

          <section class="panel chat-panel">
            <div class="panel-heading compact">
              <div>
                <span class="panel-kicker">01 / CONVERSATION</span>
                <h2>{{ activeSession?.title ?? '新的协同对话' }}</h2>
              </div>
              <span class="policy-tag">{{ activeSession?.status ?? 'IDLE' }}</span>
            </div>

            <div ref="transcriptEl" class="chat-transcript">
              <div v-if="!activeSession" class="muted-empty">先创建一个对话，然后描述你想做的实验。</div>
              <template v-else>
                <p v-if="!activeSession.messages.length" class="chat-hint">
                  例如：「把目标数改成 5，用卡尔曼滤波跑一次，再比较两种调度策略的跟踪表现」。
                </p>

                <div
                  v-for="message in activeSession.messages"
                  :key="message.message_id"
                  class="chat-message"
                  :class="`role-${message.role}`"
                >
                  <template v-if="message.role === 'user'">
                    <div class="chat-author"><span>你</span></div>
                    <div class="chat-bubble">{{ message.content }}</div>
                  </template>

                  <template v-else-if="message.role === 'assistant'">
                    <div class="chat-author">
                      <span>{{ message.produced_by === 'rule' ? '本地规则规划器' : (message.produced_by || 'Agent') }}</span>
                      <em v-if="message.produced_by === 'rule'">规则模式 · 并非模型生成</em>
                    </div>
                    <div v-if="message.content" class="chat-bubble assistant">{{ message.content }}</div>
                    <div v-if="message.knowledge?.length" class="chat-sources">
                      <span class="sources-label">依据平台资料</span>
                      <span v-for="source in message.knowledge" :key="source.chunk_id" class="source-chip">
                        {{ source.title }}
                      </span>
                    </div>
                    <div v-for="call in message.tool_calls" :key="call.call_id" class="chat-tool-intent">
                      调用 <strong>{{ agentToolLabel(call.name) }}</strong>
                      <span v-if="call.arguments.reason"> · {{ call.arguments.reason }}</span>
                    </div>
                  </template>

                  <template v-else>
                    <div class="chat-tool-card" :class="{ failed: message.tool_ok === false }">
                      <div class="tool-card-head">
                        <strong>{{ agentToolLabel(message.tool_name ?? '') }}</strong>
                        <span class="tool-state">{{ message.tool_ok === false ? '失败' : '完成' }}</span>
                      </div>
                      <p v-if="message.tool_ok === false" class="tool-error">{{ toolFailureText(message) }}</p>
                      <div v-if="message.evidence.length" class="agent-evidence">
                        <span v-for="item in message.evidence" :key="item.metric" class="evidence-chip">
                          {{ item.metric }}: {{ item.value }}
                        </span>
                      </div>
                      <ul v-if="message.limitations.length" class="agent-limitations">
                        <li v-for="item in message.limitations" :key="item">{{ item }}</li>
                      </ul>
                      <button
                        v-if="message.run_id"
                        class="ghost-button"
                        @click="message.run_id && openRunInWorkbench(message.run_id)"
                      >在工作台打开这次运行</button>
                    </div>
                  </template>
                </div>

                <div v-if="streamingText" class="chat-message role-assistant">
                  <div class="chat-author"><span>Agent</span><em>输入中…</em></div>
                  <div class="chat-bubble assistant">{{ streamingText }}</div>
                </div>

                <div v-if="activeSession.analysis" class="chat-analysis">
                  <div class="analysis-head">
                    <span>结构化解读 · 分析专员</span>
                    <em>{{ activeSession.analysis.produced_by ?? 'rule' }}</em>
                  </div>
                  <p class="analysis-summary">{{ activeSession.analysis.summary }}</p>
                  <div v-if="activeSession.analysis.evidence.length" class="agent-evidence">
                    <span
                      v-for="item in activeSession.analysis.evidence"
                      :key="item.metric"
                      class="evidence-chip"
                    >{{ item.metric }}: {{ item.value }}</span>
                  </div>
                  <ul v-if="activeSession.analysis.limitations.length" class="agent-limitations">
                    <li v-for="item in activeSession.analysis.limitations" :key="item">{{ item }}</li>
                  </ul>
                </div>

                <div v-if="activeSession.sequence && activeSession.pending" class="chat-plan">
                  <div class="confirm-head">实验计划 · 待确认</div>
                  <p class="plan-goal">{{ activeSession.sequence.goal }}</p>
                  <p v-if="activeSession.sequence.rationale" class="plan-rationale">{{ activeSession.sequence.rationale }}</p>
                  <ol class="plan-steps">
                    <li v-for="(step, index) in activeSession.sequence.steps" :key="index">
                      <span class="plan-step-index">{{ index + 1 }}</span>
                      <span class="plan-step-text">{{ step.summary }}</span>
                      <em class="plan-step-tool">{{ agentToolLabel(step.tool) }}</em>
                    </li>
                  </ol>
                  <div class="agent-actions">
                    <button class="primary-button" :disabled="sessionBusy" @click="decidePendingTool(true)">执行整个计划</button>
                    <button class="secondary-button" :disabled="sessionBusy" @click="decidePendingTool(false)">拒绝</button>
                  </div>
                </div>

                <div v-else-if="activeSession.pending" class="chat-confirm">
                  <div class="confirm-head">需要你的确认</div>
                  <p>{{ activeSession.pending.prompt }}</p>
                  <ul>
                    <li v-for="call in activeSession.pending.tool_calls" :key="call.call_id">{{ agentToolLabel(call.name) }}</li>
                  </ul>
                  <div class="agent-actions">
                    <button class="primary-button" :disabled="sessionBusy" @click="decidePendingTool(true)">执行</button>
                    <button class="secondary-button" :disabled="sessionBusy" @click="decidePendingTool(false)">拒绝</button>
                  </div>
                </div>

                <div v-if="sessionBusy && !activeSession.pending" class="chat-busy">{{ liveStage ?? 'Agent 正在工作…' }}</div>
              </template>
            </div>

            <div class="chat-composer">
              <textarea
                v-model="composerText"
                rows="3"
                :disabled="!activeSession || sessionBusy"
                placeholder="描述你的实验目标，例如：把目标数改成 5，用卡尔曼滤波跑一次"
                @keydown.enter.exact.prevent="sendChatMessage"
              ></textarea>
              <div class="composer-actions">
                <span class="composer-hint">Enter 发送 · Shift+Enter 换行</span>
                <button class="primary-button" :disabled="!canSendMessage" @click="sendChatMessage">发送</button>
              </div>
            </div>
            <p v-if="chatError" class="agent-error">{{ chatError }}</p>

            <details v-if="activeSession?.events.length" class="session-event-list">
              <summary>执行轨迹（{{ activeSession.events.length }} 步）</summary>
              <div v-for="event in activeSession.events.slice(-12).reverse()" :key="event.event_id" class="session-event-row">
                <span>{{ event.event_type }}</span>
                <em>{{ shortClock(event.created_at) }}</em>
              </div>
            </details>
          </section>

        </div>
      </section>
    </main>
  </div>
</template>
