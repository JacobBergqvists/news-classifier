import { ShaderAnimation } from "@/components/ui/shader-lines"

export default function Home() {
  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-4">
      <div className="w-full max-w-4xl">
        <div className="relative flex h-[650px] w-full flex-col items-center justify-center overflow-hidden rounded-xl bg-black">
          <ShaderAnimation />
          <span className="pointer-events-none z-10 text-center text-7xl leading-none font-semibold tracking-tighter whitespace-pre-wrap text-white">
            Shader Lines
          </span>
        </div>
      </div>
    </div>
  )
}
