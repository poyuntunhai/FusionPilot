import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'

const app = createApp(App)

// A throwing render function silently freezes the whole DOM because Vue aborts
// patching. Log those loudly instead of letting the UI look "dead".
app.config.errorHandler = (error, _instance, info) => {
  console.error('[FusionPilot] unhandled error during ' + info, error)
}

app.mount('#app')