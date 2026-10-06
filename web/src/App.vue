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
let chart: echarts.ECharts | null = null
let progressTimer: number | undefined

const activeMetrics = computed(() => simulation.value?.metrics ?? null)
const currentStep = computed(() => simulation.value?.steps[activeStep.value] ?? null)
const visibleSteps = computed(() => simulation.value?.steps.slice(-12).reverse() ?? [])
const canRun = computed(() => sceneLoaded.value && !loading.value && !loadingConfig.value)

function formatNumber(value: number | undefined, digits = 2) {
  return value === undefined ? '--' : value.toFixed(digits)
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

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  activeController.value = controller
  const timeoutId = window.setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
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
      throw new Error(`Request timed out: ${url}`)
    }
    throw error
  } finally {
    window.clearTimeout(timeoutId)
    if (activeController.value === controller) {
      activeController.value = null
    }
  }
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
async function loadDefaultConfig() {
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
  } catch (error) {
    errorMessage.value = '&#26080;&#27861;&#36830;&#25509; Java &#21518;&#31471;&#65306;' + String(error)
  } finally {
    loadingConfig.value = false
  }
}

async function runSimulation() {
  if (!sceneLoaded.value) {
    errorMessage.value = '\u8bf7\u5148\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f\u3002'
    return
  }
  const token = activeRunToken.value + 1
  activeRunToken.value = token
  loading.value = true
  errorMessage.value = ''
  comparison.value = null
  beginProgress('\u5df2\u63d0\u4ea4\u4eff\u771f\u8bf7\u6c42')
  const watchdogId = window.setTimeout(() => {
    if (activeRunToken.value !== token || !loading.value) return
    activeController.value?.abort()
    loading.value = false
    clearProgress()
    progressPercent.value = 0
    progressText.value = '\u4eff\u771f\u8bf7\u6c42\u8d85\u65f6'
    errorMessage.value = '\u524d\u7aef\u7b49\u5f85 Java \u4eff\u771f\u8d85\u8fc7 5 \u79d2\u3002\u540e\u7aef\u547d\u4ee4\u884c\u6d4b\u8bd5\u80fd\u8fd4\u56de\uff0c\u8bf7\u91cd\u542f\u524d\u7aef dev \u670d\u52a1\u6216\u5237\u65b0\u9875\u9762\u540e\u518d\u8bd5\u3002'
  }, 5500)
  try {
    const result = await request<SimulationResult>('/api/v1/simulations/run', {
      method: 'POST',
      body: JSON.stringify(config.value)
    })
    if (activeRunToken.value !== token) return
    progressPercent.value = 96
    progressText.value = '\u5df2\u6536\u5230\u4eff\u771f\u7ed3\u679c\uff0c\u6b63\u5728\u66f4\u65b0\u754c\u9762...'
    simulation.value = result
    activeStep.value = 0
  } catch (error) {
    if ((error as Error).name !== 'AbortError' && activeRunToken.value === token) {
      errorMessage.value = '\u4eff\u771f\u8fd0\u884c\u5931\u8d25\uff1a' + String(error)
    }
  } finally {
    window.clearTimeout(watchdogId)
    if (activeRunToken.value === token) {
      loading.value = false
    }
  }
  if (activeRunToken.value !== token) return
  await nextTick()
  try {
    renderChart()
    finishProgress('\u4eff\u771f\u5df2\u5b8c\u6210')
    void refreshSimulationDetailInBackground(simulation.value, token)
  } catch (error) {
    errorMessage.value = '\u4eff\u771f\u5df2\u5b8c\u6210\uff0c\u4f46\u8f68\u8ff9\u56fe\u6e32\u67d3\u5931\u8d25\uff1a' + String(error)
    clearProgress()
  }
}

async function comparePolicies() {
  if (!sceneLoaded.value) {
    errorMessage.value = '\u8bf7\u5148\u52a0\u8f7d\u9ed8\u8ba4\u573a\u666f\u3002'
    return
  }
  const token = activeRunToken.value + 1
  activeRunToken.value = token
  loading.value = true
  errorMessage.value = ''
  beginProgress('\u6b63\u5728\u8fd0\u884c\u4e24\u79cd\u8c03\u5ea6\u7b56\u7565')
  const watchdogId = window.setTimeout(() => {
    if (activeRunToken.value !== token || !loading.value) return
    activeController.value?.abort()
    loading.value = false
    clearProgress()
    progressPercent.value = 0
    progressText.value = '\u7b56\u7565\u5bf9\u6bd4\u8bf7\u6c42\u8d85\u65f6'
    errorMessage.value = '\u524d\u7aef\u7b49\u5f85 Java \u7b56\u7565\u5bf9\u6bd4\u8d85\u8fc7 5 \u79d2\u3002\u8bf7\u68c0\u67e5 Java \u540e\u7aef\u7ec8\u7aef\u65e5\u5fd7\u3002'
  }, 5500)
  try {
    const result = await request<ComparisonResult>('/api/v1/simulations/compare', {
      method: 'POST',
      body: JSON.stringify(config.value)
    })
    if (activeRunToken.value !== token) return
    progressPercent.value = 96
    progressText.value = '\u5bf9\u6bd4\u7ed3\u679c\u5df2\u8fd4\u56de\uff0c\u6b63\u5728\u66f4\u65b0\u754c\u9762...'
    comparison.value = result
    simulation.value = result.priority
    activeStep.value = 0
  } catch (error) {
    if ((error as Error).name !== 'AbortError' && activeRunToken.value === token) {
      errorMessage.value = '\u7b56\u7565\u5bf9\u6bd4\u5931\u8d25\uff1a' + String(error)
    }
  } finally {
    window.clearTimeout(watchdogId)
    if (activeRunToken.value === token) {
      loading.value = false
    }
  }
  if (activeRunToken.value !== token) return
  await nextTick()
  try {
    renderChart()
    finishProgress('\u7b56\u7565\u5bf9\u6bd4\u5b8c\u6210')
    void refreshSimulationDetailInBackground(simulation.value, token)
  } catch (error) {
    errorMessage.value = '\u5bf9\u6bd4\u5df2\u5b8c\u6210\uff0c\u4f46\u8f68\u8ff9\u56fe\u6e32\u67d3\u5931\u8d25\uff1a' + String(error)
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
      headers: { 'Content-Type': 'application/json' },
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

function resetAgentMessages() {
  agentMessage.value = ''
  agentError.value = ''
}

async function createAgentSession() {
  resetAgentMessages()
  agentBusy.value = true
  try {
    agentSession.value = await requestAgent<AgentTrace>('/api/v1/agent/sessions', {
      method: 'POST',
      body: JSON.stringify({
        goal: agentGoal.value,
        target_count: config.value.targetCount,
        simulation_steps: config.value.simulationSteps,
        scheduling_policy: config.value.schedulingPolicy,
        compare_policies: agentGoal.value.includes('\u6bd4\u8f83') || agentGoal.value.toLowerCase().includes('compare')
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
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
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
      <div class="topbar-status"><span class="status-dot"></span><span>&#26412;&#22320;&#20223;&#30495;</span><span class="status-divider"></span><span>JAVA &#26680;&#24515; : 8080</span></div>
    </header>

    <main class="workspace">
      <section class="intro-row">
        <div>
          <p class="eyebrow">&#22810;&#28304;&#20449;&#24687;&#34701;&#21512;</p>
          <h1>&#35266;&#27979;&#12289;&#34701;&#21512;&#19982;&#20915;&#31574;</h1>
          <p class="lede">&#36816;&#34892;&#21487;&#22797;&#29616;&#30340;&#38647;&#36798;&#36164;&#28304;&#23454;&#39564;&#65292;&#35266;&#23519;&#19981;&#30830;&#23450;&#24615;&#22914;&#20309;&#24433;&#21709;&#34701;&#21512;&#36319;&#36394;&#12290;</p>
        </div>
        <div class="run-summary"><span class="summary-label">&#36816;&#34892; ID</span><strong>{{ simulation?.runId?.slice(0, 8) ?? '--' }}</strong></div>
      </section>

      <div v-if="errorMessage" class="alert">
        <span>{{ errorMessage }}</span>
        <button class="icon-button" title="&#20851;&#38381;&#25552;&#31034;" @click="errorMessage = ''">&times;</button>
      </div>

      <section class="dashboard-grid">
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
      <section class="panel agent-panel">
        <div class="panel-heading">
          <div><span class="panel-kicker">06 / AGENT</span><h2>&#23454;&#39564;&#21327;&#20316;&#21161;&#25163;</h2></div>
          <span class="policy-tag">{{ agentSession?.status ?? '&#26410;&#24320;&#22987;' }}</span>
        </div>
        <div class="agent-layout">
          <div class="agent-compose">
            <label class="field agent-goal">
              <span>&#23454;&#39564;&#30446;&#26631;</span>
              <textarea v-model="agentGoal" rows="4" placeholder="&#25551;&#36848;&#20320;&#24819;&#27604;&#36739;&#30340;&#23454;&#39564;"></textarea>
            </label>
            <div class="agent-actions">
              <button class="secondary-button" :disabled="agentBusy || !agentGoal.trim()" @click="createAgentSession">&#29983;&#25104;&#35745;&#21010;</button>
              <button class="secondary-button" :disabled="agentBusy || !agentSession || agentSession.confirmed" @click="confirmAgentSession">&#30830;&#35748;&#35745;&#21010;</button>
            </div>
            <div v-if="agentSession" class="agent-tool-row">
              <select v-model="agentTool" :disabled="agentBusy || !agentSession.confirmed">
                <option value="validate_experiment">&#26657;&#39564;&#23454;&#39564;&#37197;&#32622;</option>
                <option value="run_simulation">&#36816;&#34892;&#20223;&#30495;</option>
                <option value="calculate_metrics">&#35745;&#31639;&#25351;&#26631;&#25688;&#35201;</option>
                <option value="compare_scheduling_policies">&#23545;&#27604;&#35843;&#24230;&#31574;&#30053;</option>
              </select>
              <button class="primary-button" :disabled="agentBusy || !agentSession.confirmed" @click="executeAgentTool">&#25191;&#34892;&#24037;&#20855;</button>
            </div>
            <p v-if="agentMessage" class="agent-message">{{ agentMessage }}</p>
            <p v-if="agentError" class="agent-error">{{ agentError }}</p>
          </div>
          <div class="agent-plan" v-if="agentSession">
            <div class="agent-plan-title">{{ agentSession.plan.title }}</div>
            <div class="agent-plan-grid">
              <div><span>&#22522;&#32447;</span><strong>{{ agentSession.plan.baselines.join(' / ') }}</strong></div>
              <div><span>&#25351;&#26631;</span><strong>{{ agentSession.plan.metrics.length }} &#39033;</strong></div>
              <div><span>&#20107;&#20214;</span><strong>{{ agentSession.events.length }}</strong></div>
            </div>
            <ol class="agent-steps">
              <li v-for="step in agentSession.plan.execution_steps" :key="step">{{ step }}</li>
            </ol>
            <button class="ghost-button trace-button" @click="refreshAgentTrace">&#21047;&#26032;&#36712;&#36857;</button>
          </div>
          <div v-else class="agent-empty">&#36755;&#20837;&#23454;&#39564;&#30446;&#26631;&#65292;&#35753; Agent &#29983;&#25104;&#21487;&#23457;&#38405;&#30340;&#35745;&#21010;&#12290;</div>
        </div>
        <div v-if="agentResult?.analysis" class="agent-analysis">
          <div class="subsection-title">&#32467;&#26524;&#35299;&#37322;</div>
          <p>{{ agentResult.analysis.summary }}</p>
          <div class="agent-evidence">
            <span v-for="item in agentResult.analysis.evidence" :key="item.metric" class="evidence-chip">{{ item.metric }}: {{ item.value }}</span>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>