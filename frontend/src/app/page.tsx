'use client'

import { useState, useEffect } from 'react'
import { SignInButton, SignOutButton, UserButton, ClerkLoaded, useAuth } from "@clerk/clerk-react";
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Campaign {
  id: number
  name: string
  value_proposition: string
  cta: string
  status: string
}

export default function Home() {
  const { isLoaded, userId, getToken } = useAuth()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [selectedCampaign, setSelectedCampaign] = useState<string>('')
  
  // State for logs
  const [activeTab, setActiveTab] = useState<'outreach' | 'monitor'>('outreach')
  const [outreachLogs, setOutreachLogs] = useState<{status: string, message: string}[]>([])
  const [monitorLogs, setMonitorLogs] = useState<{status: string, message: string}[]>([])
  
  const [isStreaming, setIsStreaming] = useState(false)
  const [isMonitoring, setIsMonitoring] = useState(false)

  // Start Email Monitor SSE connection
  useEffect(() => {
    if (isLoaded && userId && activeTab === 'monitor' && !isMonitoring) {
      let eventSource: EventSource | null = null;
      const connectMonitor = async () => {
        try {
          const token = await getToken()
          if (!token) return;
          
          const url = new URL(`${API_BASE}/api/webhooks/stream`)
          url.searchParams.append('token', token)
          
          eventSource = new EventSource(url.toString())
          setIsMonitoring(true)
          
          eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data)
            setMonitorLogs(prev => [...prev, data])
          }
          
          eventSource.onerror = (err) => {
            console.error('Monitor EventSource failed:', err)
            setIsMonitoring(false)
            eventSource?.close()
          }
        } catch (err) {
          console.error('Failed to connect to monitor:', err)
        }
      }
      connectMonitor()
      
      return () => {
        if (eventSource) {
          eventSource.close()
          setIsMonitoring(false)
        }
      }
    }
  }, [isLoaded, userId, activeTab, getToken])

  useEffect(() => {
    if (isLoaded && userId) {
      const loadCampaigns = async () => {
        try {
          const token = await getToken()
          const res = await fetch(`${API_BASE}/api/campaigns`, {
            headers: {
              'Authorization': `Bearer ${token}`
            }
          })
          const data = await res.json()
          setCampaigns(data.campaigns || [])
        } catch (err) {
          console.error('Error fetching campaigns:', err)
        }
      }
      loadCampaigns()
    }
  }, [isLoaded, userId, getToken])

  const startOutreach = async () => {
    setOutreachLogs([])
    setIsStreaming(true)
    setActiveTab('outreach')
    
    try {
      const token = await getToken()
      const url = new URL(`${API_BASE}/api/outreach/stream`)
      if (selectedCampaign) {
        url.searchParams.append('campaign_name', selectedCampaign)
      }
      if (token) {
        url.searchParams.append('token', token)
      }

      const eventSource = new EventSource(url.toString())

      eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data)
        setOutreachLogs(prev => [...prev, data])
        
        if (data.status === 'success' || data.status === 'error') {
          eventSource.close()
          setIsStreaming(false)
        }
      }

      eventSource.onerror = (err) => {
        console.error('EventSource failed:', err)
        setOutreachLogs(prev => [...prev, { status: 'error', message: 'Connection to server lost or unauthorized' }])
        eventSource.close()
        setIsStreaming(false)
      }
    } catch (err) {
      console.error('Failed to start outreach:', err)
      setIsStreaming(false)
    }
  }

  if (!isLoaded) {
    return <div className="flex items-center justify-center min-h-screen">Loading...</div>
  }

  return (
    <div className="flex flex-col min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="flex items-center justify-between px-8 py-4 bg-white border-b border-zinc-200 dark:bg-zinc-900 dark:border-zinc-800">
        <div className="flex items-center gap-6">
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-50">Shiku SDR</h1>
          {userId && (
            <nav className="flex gap-4">
              <Link href="/" className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Dashboard</Link>
              <Link href="/campaigns" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Campaigns</Link>
              <Link href="/leads" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Leads</Link>
              <Link href="/drafts" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Drafts</Link>
              <Link href="/staff" className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">Staff</Link>
            </nav>
          )}
        </div>
        <div className="flex items-center gap-4">
          <ClerkLoaded>
            {userId ? (
              <UserButton />
            ) : (
              <SignInButton mode="modal">
                <button className="px-4 py-2 text-sm font-medium text-white bg-zinc-900 rounded-md hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200">
                  Sign In
                </button>
              </SignInButton>
            )}
          </ClerkLoaded>
        </div>
      </header>

      <main className="flex-1 max-w-5xl mx-auto w-full p-8">
        {!userId ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <h2 className="text-4xl font-extrabold text-zinc-900 dark:text-zinc-50 mb-4">
              Enterprise SDR AI
            </h2>
            <p className="text-lg text-zinc-600 dark:text-zinc-400 max-w-xl mb-8">
              Automate your outbound sales with intelligent orchestrator-worker agents. 
              Sign in to manage campaigns and monitor real-time outreach.
            </p>
            <SignInButton mode="modal">
              <button className="px-8 py-3 text-lg font-semibold text-white bg-zinc-900 rounded-full hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200 transition-all shadow-lg">
                Get Started
              </button>
            </SignInButton>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Control Panel */}
            <div className="md:col-span-1 space-y-6">
              <div className="p-6 bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800">
                <h2 className="text-lg font-semibold mb-4 text-zinc-900 dark:text-zinc-50">Campaign Control</h2>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Select Campaign
                    </label>
                    <select 
                      value={selectedCampaign}
                      onChange={(e) => setSelectedCampaign(e.target.value)}
                      className="w-full px-3 py-2 bg-zinc-50 border border-zinc-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-zinc-500 dark:bg-zinc-800 dark:border-zinc-700"
                    >
                      <option value="">Random Active Campaign</option>
                      {campaigns.map(camp => (
                        <option key={camp.id} value={camp.name}>{camp.name}</option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={startOutreach}
                    disabled={isStreaming}
                    className="w-full py-2 bg-zinc-900 text-white rounded-lg font-medium hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200 transition-colors"
                  >
                    {isStreaming ? 'AI Agent Working...' : 'Run Outreach'}
                  </button>
                </div>
              </div>

              <div className="p-6 bg-white border border-zinc-200 rounded-xl shadow-sm dark:bg-zinc-900 dark:border-zinc-800">
                <h3 className="text-sm font-semibold mb-2 text-zinc-500 uppercase tracking-wider">Stats</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{campaigns.length}</p>
                    <p className="text-xs text-zinc-500">Active Campaigns</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Logs/Terminal */}
            <div className="md:col-span-2 flex flex-col gap-4">
              {/* Tab Navigation */}
              <div className="flex border-b border-zinc-200 dark:border-zinc-800">
                <button
                  className={`px-4 py-2 text-sm font-medium ${activeTab === 'outreach' ? 'border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100' : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'}`}
                  onClick={() => setActiveTab('outreach')}
                >
                  Outreach Orchestrator
                </button>
                <button
                  className={`px-4 py-2 text-sm font-medium ${activeTab === 'monitor' ? 'border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100' : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'}`}
                  onClick={() => setActiveTab('monitor')}
                >
                  Email Monitor
                  {isMonitoring && <span className="ml-2 inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>}
                </button>
              </div>

              <div className="flex-1 min-h-[500px] flex flex-col bg-zinc-900 rounded-xl border border-zinc-800 overflow-hidden shadow-xl">
                <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800 bg-zinc-900/50">
                  <div className="w-3 h-3 rounded-full bg-red-500/20 border border-red-500/50"></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500/20 border border-yellow-500/50"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500/20 border border-green-500/50"></div>
                  <span className="ml-2 text-xs font-mono text-zinc-500">
                    {activeTab === 'outreach' ? 'orchestrator-logs' : 'monitor-logs'}
                  </span>
                </div>
                <div className="flex-1 p-4 font-mono text-sm overflow-y-auto space-y-2">
                  {activeTab === 'outreach' ? (
                    <>
                      {outreachLogs.length === 0 && !isStreaming && (
                        <p className="text-zinc-600 italic">Ready to execute outreach campaign...</p>
                      )}
                      {outreachLogs.map((log: any, i: number) => (
                        <div key={i} className={`flex gap-3 ${
                          log.status === 'error' ? 'text-red-400' : 
                          log.status === 'success' ? 'text-emerald-400' : 
                          log.status === 'warning' ? 'text-yellow-400' :
                          'text-zinc-300'
                        }`}>
                          <span className="text-zinc-600">[{new Date().toLocaleTimeString()}]</span>
                          <span>{log.message}</span>
                        </div>
                      ))}
                      {isStreaming && (
                        <div className="flex gap-3 text-zinc-400 animate-pulse">
                          <span className="text-zinc-600">[{new Date().toLocaleTimeString()}]</span>
                          <span>AI Agent is thinking...</span>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      {monitorLogs.length === 0 && !isMonitoring && (
                        <p className="text-zinc-600 italic">Connecting to Email Monitor...</p>
                      )}
                      {monitorLogs.length === 0 && isMonitoring && (
                        <p className="text-zinc-600 italic">Listening for incoming webhooks...</p>
                      )}
                      {monitorLogs.map((log: any, i: number) => (
                        <div key={i} className={`flex gap-3 ${
                          log.status === 'error' ? 'text-red-400' : 
                          log.status === 'success' ? 'text-emerald-400' : 
                          log.status === 'warning' ? 'text-yellow-400' :
                          'text-zinc-300'
                        }`}>
                          <span className="text-zinc-600 shrink-0">[{new Date().toLocaleTimeString()}]</span>
                          {log.event_id && (
                            <span className="text-violet-400 font-mono text-xs shrink-0">[{log.event_id}]</span>
                          )}
                          <span>{log.message}</span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      <footer className="py-6 px-8 border-t border-zinc-200 dark:border-zinc-800 text-center text-xs text-zinc-500">
        © 2026 Shiku SDR Platform • Powered by Andela AI
      </footer>
    </div>
  )
}
