import { useState, useRef, useCallback } from 'react';
import { pipeline, env, AutoProcessor, Idefics3ForConditionalGeneration, RawImage } from '@huggingface/transformers';

// 直接从 HuggingFace 加载模型（浏览器可直接访问）
env.allowLocalModels = false;
env.useBrowserCache = true;

// 使用 CDN 加载 ONNX Runtime WebAssembly 文件，避免打包超过 25MiB 限制的 wasm
env.backends.onnx.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.0/dist/';
env.backends.onnx.wasm.numThreads = 1;

type ModelType = 'text' | 'vision';

interface ModelOption {
  id: string;
  label: string;
  type: ModelType;
  task: 'text-generation' | 'image-to-text';
  size: string;
  description: string;
}

// 可选模型列表
const MODELS: ModelOption[] = [
  {
    id: 'HuggingFaceTB/SmolLM-135M-Instruct',
    label: 'SmolLM-135M（纯文本，最小）',
    type: 'text',
    task: 'text-generation',
    size: '约 270MB',
    description: '纯文本语言模型，用于验证 WebGPU 推理链路是否通畅',
  },
  {
    id: 'HuggingFaceTB/SmolVLM-256M-Instruct',
    label: 'SmolVLM-256M（多模态）',
    type: 'vision',
    task: 'image-to-text',
    size: '约 500MB-1GB',
    description: '视觉语言模型（Idefics3 架构），输入图像，输出文本描述',
  },
];

interface TestResult {
  model: string;
  loadTimeMs: number;
  inferenceTimeMs: number;
  outputText: string;
  tokensPerSecond?: number;
}

/**
 * 浏览器端模型推理可行性验证组件
 * 支持纯文本和多模态两种模型测试
 */
export default function SmolVLMTester() {
  const [status, setStatus] = useState<string>('待测试');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [webgpuSupported, setWebgpuSupported] = useState<boolean | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>(MODELS[0].id);
  const pipeRef = useRef<any>(null);

  // 检测 WebGPU 支持
  const checkWebGPU = useCallback(async () => {
    const gpu = (navigator as any).gpu;
    if (!gpu) {
      setWebgpuSupported(false);
      return false;
    }
    try {
      const adapter = await gpu.requestAdapter();
      setWebgpuSupported(!!adapter);
      return !!adapter;
    } catch {
      setWebgpuSupported(false);
      return false;
    }
  }, []);

  // 运行推理测试
  const runTest = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setStatus('正在检测 WebGPU...');

    const hasWebGPU = await checkWebGPU();
    if (!hasWebGPU) {
      setError('当前浏览器不支持 WebGPU，无法运行 GPU 加速推理。请使用最新版 Chrome/Edge。');
      setStatus('测试失败');
      setIsLoading(false);
      return;
    }

    const modelOpt = MODELS.find((m) => m.id === selectedModel)!;

    try {
      setStatus(`正在加载 ${modelOpt.label}（首次需下载，${modelOpt.size}）...`);

      const loadStart = performance.now();

      let output: any;
      let loadTimeMs = 0;
      const inferStart = performance.now();

      if (modelOpt.type === 'text') {
        // 纯文本模型：使用 pipeline
        const pipe = (await pipeline(modelOpt.task, modelOpt.id, {
          device: 'webgpu',
          dtype: 'q8',
        })) as any;
        loadTimeMs = performance.now() - loadStart;
        pipeRef.current = pipe;
        setStatus('模型加载完成，正在推理...');

        const messages = [
          { role: 'user', content: 'Hello, can you tell me what is 2 + 2?' },
        ];
        output = await pipe(messages, { max_new_tokens: 100 });
      } else {
        // 多模态模型：使用底层 API（AutoProcessor + Idefics3ForConditionalGeneration）
        const processor = await AutoProcessor.from_pretrained(modelOpt.id);
        const model = await Idefics3ForConditionalGeneration.from_pretrained(modelOpt.id, {
          device: 'webgpu',
          dtype: 'q8',
        });
        loadTimeMs = performance.now() - loadStart;
        setStatus('模型加载完成，正在推理...');

        // 生成测试图像
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext('2d')!;
        const gradient = ctx.createLinearGradient(0, 0, 256, 256);
        gradient.addColorStop(0, '#ff0000');
        gradient.addColorStop(1, '#0000ff');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, 256, 256);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(80, 80, 96, 96);

        // 将 canvas 转为 RawImage
        const image = await RawImage.fromCanvas(canvas);

        // 构建对话消息
        const conversation = [
          {
            role: 'user',
            content: [
              { type: 'image' },
              { type: 'text', text: 'Describe this image in detail.' },
            ],
          },
        ];

        // 处理输入：直接在 apply_chat_template 中完成 tokenize
        const inputs = (await processor.apply_chat_template(conversation, {
          add_generation_prompt: true,
          tokenize: true,
          return_dict: true,
          return_tensors: 'pt',
          images: [image],
        } as any)) as Record<string, any>;

        // 生成输出
        const outputIds = await model.generate({
          ...inputs,
          max_new_tokens: 100,
        });

        // 解码输出
        output = processor.batch_decode(outputIds as any, { skip_special_tokens: true });
      }

      const inferenceTimeMs = performance.now() - inferStart;

      // 先查看原始输出结构，再提取文本
      let outputText = '';
      try {
        // 递归提取所有字符串内容
        const extractText = (val: any): string => {
          if (val === null || val === undefined) return '';
          if (typeof val === 'string') return val;
          if (typeof val === 'number' || typeof val === 'boolean') return String(val);
          if (Array.isArray(val)) return val.map(extractText).filter(Boolean).join('\n');
          if (typeof val === 'object') {
            if (val.content) return extractText(val.content);
            if (val.generated_text) return extractText(val.generated_text);
            if (val.text) return extractText(val.text);
            // 否则序列化整个对象
            return JSON.stringify(val, null, 2);
          }
          return String(val);
        };
        outputText = extractText(output);
      } catch {
        outputText = JSON.stringify(output, null, 2);
      }
      // 强制确保是字符串
      outputText = String(outputText);

      // 粗略估算 tokens/s（按 4 字符/token 估算）
      const estimatedTokens = outputText.length / 4;
      const tokensPerSecond = inferenceTimeMs > 0 ? (estimatedTokens / (inferenceTimeMs / 1000)) : 0;

      setResult({
        model: modelOpt.id,
        loadTimeMs,
        inferenceTimeMs,
        outputText,
        tokensPerSecond,
      });
      setStatus('测试完成');
    } catch (err: any) {
      console.error(err);
      setError(err?.message || '推理失败');
      setStatus('测试失败');
    } finally {
      setIsLoading(false);
    }
  }, [checkWebGPU, selectedModel]);

  const currentModel = MODELS.find((m) => m.id === selectedModel)!;

  return (
    <div style={{ padding: 20, maxWidth: 800, margin: '0 auto' }}>
      <h2>浏览器端模型推理可行性验证</h2>

      <div style={{ marginBottom: 16 }}>
        <strong>WebGPU 支持：</strong>
        {webgpuSupported === null ? '未检测' : webgpuSupported ? '✅ 支持' : '❌ 不支持'}
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', marginBottom: 6 }}>
          <strong>选择测试模型：</strong>
        </label>
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          disabled={isLoading}
          style={{
            padding: '8px 12px',
            fontSize: 14,
            borderRadius: 4,
            border: '1px solid #334155',
            background: '#0f172a',
            color: '#e2e8f0',
            minWidth: 320,
          }}
        >
          {MODELS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>
          {currentModel.description}（{currentModel.size}）
        </p>
      </div>

      <button
        onClick={runTest}
        disabled={isLoading}
        style={{
          padding: '10px 20px',
          fontSize: 16,
          cursor: isLoading ? 'not-allowed' : 'pointer',
          background: isLoading ? '#999' : '#4CAF50',
          color: 'white',
          border: 'none',
          borderRadius: 4,
        }}
      >
        {isLoading ? '测试中...' : '开始测试'}
      </button>

      <div style={{ marginTop: 16, padding: 12, background: '#1e293b', borderRadius: 4 }}>
        <strong>状态：</strong>{status}
      </div>

      {error && (
        <div style={{ marginTop: 16, padding: 12, background: '#7f1d1d', borderRadius: 4, color: '#fca5a5' }}>
          <strong>错误：</strong>{error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 16, padding: 16, background: '#14532d', borderRadius: 4 }}>
          <h3>测试结果</h3>
          <ul>
            <li><strong>模型：</strong>{result.model}</li>
            <li><strong>加载时间：</strong>{(result.loadTimeMs / 1000).toFixed(2)} 秒</li>
            <li><strong>推理时间：</strong>{result.inferenceTimeMs.toFixed(0)} 毫秒</li>
            <li><strong>估算速度：</strong>{result.tokensPerSecond?.toFixed(1)} tokens/秒</li>
          </ul>
          <div>
            <strong>输出文本：</strong>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#0f172a', padding: 8, borderRadius: 4, maxHeight: 300, overflowY: 'auto' }}>
              {result.outputText}
            </pre>
          </div>
        </div>
      )}

      <div style={{ marginTop: 24, padding: 12, background: '#78350f', borderRadius: 4, fontSize: 14 }}>
        <strong>说明：</strong>
        <ul>
          <li>首次运行需从 HuggingFace 下载模型，后续会缓存到浏览器</li>
          <li>推理在浏览器端通过 WebGPU 完成，不占用服务器资源</li>
          <li>如遇下载问题，可配置 HF_ENDPOINT 环境变量使用镜像</li>
          <li>建议先测试 SmolLM-135M 确认 WebGPU 链路通畅，再测试多模态模型</li>
        </ul>
      </div>
    </div>
  );
}
