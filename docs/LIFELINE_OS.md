# LIFELINE OS — arquitectura de coordinación humanitaria

> **Dado lo que sabemos, ¿cómo coordinamos mejor la ayuda sin ocultar la incertidumbre?**

LIFELINE no se presenta como “una IA para desastres”, ni como un dashboard,
ni como un chatbot. Es infraestructura abierta para apoyar la coordinación
humanitaria durante una crisis.

Su propósito es convertir hechos operativos verificables —reportes, recursos,
rutas, capacidad y aprobaciones— en propuestas explicables que una persona
autorizada puede revisar, aprobar, corregir o rechazar.

No reemplaza a las autoridades, a los equipos de emergencia, a los protocolos
locales ni al juicio humano.

## El principio rector

```text
Datos
    ↓
Validación
    ↓
Planificación determinista
    ↓
Aprobación humana
    ↓
Narración opcional
```

ChatGPT puede narrar un plan aprobado y responder sobre evidencia ya
seleccionada. No puede seleccionar recursos, alterar prioridades, inventar
ubicaciones, afirmar hechos no verificados, emitir órdenes ni dar consejo
operativo como autoridad.

Si el modelo no está disponible o falla, el plan y su auditoría siguen
existiendo.

## Evidencia no es relato

En una inundación pueden coexistir afirmaciones incompatibles:

- una persona informa que el puente cayó;
- otra afirma que hay cien personas atrapadas;
- un dron reciente muestra el puente en pie;
- una imagen satelital tiene cuatro horas de antigüedad.

LIFELINE no convierte ese conjunto en una afirmación falsa de certeza. Su
salida debe conservar la tensión:

```text
Estado de ruta: EN CONFLICTO
Fuentes: 3 reportes contradictorios
Frescura: baja / media / alta, por fuente
Consecuencia: no se genera propuesta que dependa de la ruta
Siguiente acción: verificación aérea o confirmación de una fuente autorizada
```

La incertidumbre es información operacional. Se registra, se muestra y puede
bloquear una propuesta; nunca se oculta para que el mapa parezca completo.

## LIFELINE como sistema operativo de crisis

```text
LIFELINE OS
│
├── Emergency Kernel
│   ├── hechos, restricciones y estados operativos
│   ├── planificación reproducible
│   ├── aprobación humana y roles
│   └── auditoría verificable
│
├── Maps
├── Resources
├── Hospitals
├── Shelters
├── Volunteers
├── Communications
├── Drones and sensors
├── Verification
├── Logistics
└── AI assistants
```

Los asistentes de IA son aplicaciones dentro del sistema, no su centro de
autoridad. El *Emergency Kernel* debe seguir funcionando sin ellos.

## Contrato de datos mínimo

Toda entidad que pueda afectar un plan necesita procedencia y estado, no sólo
coordenadas bonitas en un mapa.

### Reporte

```text
report_id
source
source_type
created_at / observed_at / received_at
location and precision
claim type
verification_state
freshness
contradictions
custody_hash
```

### Recurso

```text
resource_id
kind and capability
availability
current zone
capacity
operating constraints
source and last confirmation
```

### Ruta y destino

```text
route_id / origin / destination
route_state
source and freshness
estimated travel time
alternate routes

shelter_id / open beds / accessibility / status
hospital_id / relevant capacity / status
```

### Propuesta

```text
proposal_id
facts considered
constraints satisfied
options discarded and why
uncertainties that prevented options
approval_state
approver and timestamp
trace_hash
```

## El núcleo no optimiza personas

LIFELINE no asigna un valor humano a las personas ni produce una función de
“vidas máximas”. El núcleo trabaja sobre restricciones operativas definidas y
revisables por quienes gestionan la emergencia:

- no superar la capacidad de un refugio u hospital;
- no usar un recurso no disponible o no compatible;
- no depender de una ruta cerrada, vencida o en conflicto;
- minimizar el tiempo de llegada entre alternativas viables;
- preservar cobertura mínima entre zonas;
- tratar necesidades críticas sólo cuando estén verificadas bajo el protocolo
  aplicable;
- mantener rutas y recursos alternativos;
- abstenerse cuando falte información necesaria.

El resultado es una **propuesta factible**, nunca una orden automática.

## Simulación: presentar alternativas, no elegir por la gente

Mientras el equipo coordina, LIFELINE puede evaluar planes contra escenarios
explícitos y simulados:

```text
Plan A → refugio mantiene capacidad, ruta disponible
Plan B → mejor cobertura bajo demora de ambulancia
Plan C → falla si el puente norte se confirma cerrado
Plan D → requiere capacidad hospitalaria adicional
```

La simulación sirve para revelar dependencias y fragilidades. No debe producir
un “ganador” opaco ni sustituir a quien conoce la situación local.

Cada resultado debe declarar:

- supuestos del escenario;
- datos y marcas de tiempo usados;
- restricciones activas;
- recursos no modelados;
- qué cambió entre planes;
- límites del modelo.

En una versión inicial, estos escenarios se ejecutan sólo sobre datos
sintéticos o sobre datos operativos explícitamente autorizados para simulación.

## Presupuesto de verificación: Thompson Sampling fuera de la autoridad

Una crisis puede tener muchos reportes y poco tiempo para verificarlos. El
algoritmo bayesiano de MUTANTE puede inspirar un **Verification Budget
Allocator**: una herramienta que propone qué acción de verificación podría
reducir más incertidumbre operacional.

Ejemplos de acciones candidatas:

- llamar a una fuente;
- contrastar capacidad de un refugio;
- pedir una foto geolocalizada;
- consultar un estado de ruta;
- verificar un sensor;
- solicitar confirmación a un equipo local.

No puede seleccionar quién recibe ayuda, imponer una prioridad de rescate ni
enviar una orden. Su dominio es la **cola de preguntas verificables**, no el
despacho.

### Adopción segura del bandit

1. **Laboratorio offline:** campañas sobre crisis sintéticas e históricas,
   sin efecto operacional.
2. **Modo sombra:** genera propuestas de verificación que se comparan con el
   trabajo humano, sin mostrarse como autoridad.
3. **Asistencia visible:** una persona elige si usar la propuesta. Su rechazo
   es una salida válida, no un error.

Como Thompson Sampling es probabilístico, cada recomendación debe registrar:

```text
policy version
random seed
posterior by arm
available evidence
proposed verification
observed outcome
human approval or rejection
```

El planificador de recursos permanece determinista. Un componente
probabilístico nunca puede esconderse dentro de sus criterios.

## Patrones rescatables del ecosistema

Estos proyectos aportan ideas; LIFELINE no debe acoplar repositorios enteros
ni importar capacidades fuera de su dominio.

| Origen | Idea que se rescata | Uso responsable en LIFELINE |
|---|---|---|
| MNEME | Custodia por memoria, cuarentena, verificador offline | Cadena de custodia por reporte; un reporte no confiable no puede influir en el plan. |
| CRONOS | Trazas de decisión mientras ocurren | Hechos, restricciones, descartes y aprobación de cada propuesta. |
| Audit Chain | Exportación y verificación independiente | Línea de tiempo verificable del incidente; futura capa HMAC o anclaje externo. |
| STIGMERGY | Consenso distribuido, cooldowns, Merkle ledger | Futuras células locales/ONG sin coordinador único; evitar oscilación de recursos. |
| VIGÍA | Abstención, límites explícitos, evidencia antes que relato | Mostrar conflictos y ausencia de información como incertidumbre, no certeza. |
| CORVUS | Corroboración independiente y baseline | Validadores de frescura, duplicado, ubicación y contradicción; no análisis psicológico de víctimas. |
| raven-memory | Degradación visible y memoria de campo | Base de conocimientos posterior al incidente, con calidad semántica declarada. |
| STYLOMETRY-CI | Consistencia de fuentes | Posible monitoreo opt-in de fuentes institucionales/sensores, nunca perfilado de víctimas. |
| MUTANTE | Campañas adversariales y Thompson Sampling | Laboratorio de reportes conflictivos, duplicados, inyección y presupuesto de verificación. |
| PHYLO | Competencia reproducible de alternativas | Evaluar políticas en sandbox y adoptar sólo mejoras medibles y revisadas. |
| JANUS | Proporcionalidad, proceso antes que culpa | Diseñar para operadores bajo presión sin vigilancia invasiva ni juicio individual. |

## Límites éticos no negociables

- No despachos automáticos.
- No predicción de supervivencia ni “valor” de una persona.
- No biometría, clonación de voz o identidad de víctimas.
- No perfilado psicológico de víctimas, voluntariado o personal.
- No presentar datos simulados como hechos en vivo.
- No ocultar fuentes vencidas, conflictos o ausencia de cobertura.
- No enviar contenido sensible a un modelo sin una política, aviso y
  autorización explícita.
- No usar una narración generada como evidencia original.

## Primera secuencia de construcción

1. **Emergency Kernel**: contratos de datos, restricciones duras, estados de
   aprobación y abstención.
2. **Incident Room**: mapa de una inundación sintética, recursos, rutas,
   refugios y propuesta explicable.
3. **Custodia mínima**: reportes con fuente/frescura/estado y trazas de plan.
4. **Simulación de alternativas**: planes comparables con supuestos visibles.
5. **Laboratorio adversarial**: datos duplicados, fuentes contradictorias,
   rutas imposibles e inyección de texto.
6. **Narración opcional**: sólo después de que el núcleo y una persona hayan
   producido el plan aprobado.

## Promesa de producto

LIFELINE no promete conocer una crisis completa ni tomar decisiones humanas.
Promete algo más honesto y útil:

> Esto es lo que sabemos. Esto es lo que no sabemos. Estas son las opciones
> factibles. Esta es la evidencia que las sostiene. Y ésta es la persona que
> aprobó la acción.
