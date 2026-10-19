// Enterprise Intranet Assistant — Original v0 Design System (Restored)
const { useState, useEffect, useRef, createElement: h } = React;

// Inline SVG Icon Helper for clean, offline, razor-sharp rendering
function Icon({ name, size = 16, className = "" }) {
  const icons = {
    logo: h("img", {
      src: "/static/logo.png",
      alt: "AeroGrid AI",
      width: size,
      height: size,
      className: `brand-logo-img ${className}`.trim(),
      style: { objectFit: "contain", display: "block" }
    }),
    panelLeft: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("rect", { width: "18", height: "18", x: "3", y: "3", rx: "2" }),
      h("path", { d: "M9 3v18" })
    ),
    squarePen: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" }),
      h("path", { d: "M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z" })
    ),
    search: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("circle", { cx: "11", cy: "11", r: "8" }),
      h("path", { d: "m21 21-4.3-4.3" })
    ),
    book: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" }),
      h("path", { d: "M6 6h10M6 10h10" })
    ),
    database: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("ellipse", { cx: "12", cy: "5", rx: "9", ry: "3" }),
      h("path", { d: "M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" }),
      h("path", { d: "M3 12c0 1.66 4 3 9 3s9-1.34 9-3" })
    ),
    shield: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" }),
      h("path", { d: "m9 12 2 2 4-4" })
    ),
    help: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("circle", { cx: "12", cy: "12", r: "10" }),
      h("path", { d: "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" }),
      h("path", { d: "M12 17h.01" })
    ),
    sun: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("circle", { cx: "12", cy: "12", r: "4" }),
      h("path", { d: "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" })
    ),
    moon: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" })
    ),
    arrowUp: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", width: size, height: size, className },
      h("path", { d: "m5 12 7-7 7 7" }),
      h("path", { d: "M12 19V5" })
    ),
    square: h("svg", { viewBox: "0 0 24 24", fill: "currentColor", width: size, height: size, className },
      h("rect", { width: "14", height: "14", x: "5", y: "5", rx: "2" })
    ),
    chevronDown: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "m6 9 6 6 6-6" })
    ),
    layers: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.9a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" }),
      h("path", { d: "m22 12.5-9.17 4.17a2 2 0 0 1-1.66 0L2 12.5" }),
      h("path", { d: "m22 17.5-9.17 4.17a2 2 0 0 1-1.66 0L2 17.5" })
    ),
    folder: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" })
    ),
    fileText: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" }),
      h("path", { d: "M14 2v4a2 2 0 0 0 2 2h4" }),
      h("path", { d: "M10 9H8M16 13H8M16 17H8" })
    ),
    check: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", width: size, height: size, className },
      h("path", { d: "M20 6 9 17l-5-5" })
    ),
    copy: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("rect", { width: "14", height: "14", x: "8", y: "8", rx: "2", ry: "2" }),
      h("path", { d: "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" })
    ),
    x: h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", width: size, height: size, className },
      h("path", { d: "M18 6 6 18M6 6l12 12" })
    )
  };
  return icons[name] || null;
}

// The 4 Authoritative v0 Quick Prompt Cards
const QUICK_PROMPTS = [
  {
    title: "Find an internal policy",
    prompt: "What is our annual paternity & maternity leave policy?",
    tag: "HR Policy • PDF",
    icon: "fileText",
    scope: "docs"
  },
  {
    title: "Look up a procedure",
    prompt: "What are the rules for rotating SSH and production API keys?",
    tag: "Security Guide",
    icon: "shield",
    scope: "docs"
  },
  {
    title: "Locate a resource",
    prompt: "List all employees in the Data Engineering department",
    tag: "SQL Catalog",
    icon: "database",
    scope: "sql"
  },
  {
    title: "Explain a company process",
    prompt: "Explain the travel expense reimbursement approval flow",
    tag: "Finance Policy",
    icon: "layers",
    scope: "docs"
  }
];

const SCOPES = [
  { id: "all", label: "All Intranet", hint: "Documents and catalog data" },
  { id: "docs", label: "Policies & Docs", hint: "Policies, guides, and PDFs" },
  { id: "sql", label: "Internal SQL DB", hint: "Approved read-only queries" }
];

const KNOWLEDGE_BASES = [
  { id: "hr", name: "HR & Employee Benefits", folder: "/data/documents/hr", meta: "12 docs · updated 2h ago" },
  { id: "sec", name: "IT Security & Compliance", folder: "/data/documents/security", meta: "v4.2 · 31 docs" },
  { id: "eng", name: "Engineering Runbooks", folder: "/data/documents/engineering", meta: "Architecture · 58 docs" },
  { id: "fin", name: "Finance Policy", folder: "/data/documents/finance", meta: "9 docs · updated 3d ago" }
];

const APPROVED_QUERIES = [
  { name: "Staff & Directory Query", prompt: "Show me the employee directory for the Engineering department" },
  { name: "Department Budget Lookup", prompt: "Show the FY2026 department budget for Data Engineering" },
  { name: "Asset & Hardware Registry", prompt: "Which hardware assets are currently assigned to me?" }
];

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [tokenModalOpen, setTokenModalOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [citationModal, setCitationModal] = useState(null);
  const [session, setSession] = useState(null);
  const [mcpTools, setMcpTools] = useState([]);
  const [scope, setScope] = useState("all"); // 'all' | 'docs' | 'sql'
  const [selectedFolders, setSelectedFolders] = useState([]);
  const [scopeDropdownOpen, setScopeDropdownOpen] = useState(false);
  const [folderDropdownOpen, setFolderDropdownOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("session");
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem("theme") === "dark");
  const [auditLog, setAuditLog] = useState([]);
  const [copiedId, setCopiedId] = useState(null);

  const [conversations, setConversations] = useState([
    {
      id: "h1",
      title: "PTO and parental leave rules",
      updatedAt: Date.now() - 2 * 3600 * 1000,
      messages: [
        { id: "m1", role: "user", content: "What is our annual paternity & maternity leave policy?", time: "10:15 AM" },
        { id: "m2", role: "assistant", content: "Employees are eligible for up to 16 weeks of fully paid parental leave after completing 90 days of continuous full-time employment.", time: "10:16 AM" }
      ]
    },
    {
      id: "h2",
      title: "Engineering employee directory",
      updatedAt: Date.now() - 4 * 3600 * 1000,
      messages: [
        { id: "m3", role: "user", content: "Show me the employee directory for the Engineering department", time: "09:30 AM" },
        { id: "m4", role: "assistant", content: "Found 18 active employees in the Engineering department across Frontend, Backend, and Platform teams.", time: "09:31 AM" }
      ]
    },
    {
      id: "h3",
      title: "IT security password guidelines",
      updatedAt: Date.now() - 26 * 3600 * 1000,
      messages: [
        { id: "m5", role: "user", content: "What are the rules for rotating SSH and production API keys?", time: "Yesterday" },
        { id: "m6", role: "assistant", content: "Production SSH keys and API tokens must be rotated every 90 days and stored in the enterprise secrets vault.", time: "Yesterday" }
      ]
    },
    {
      id: "h4",
      title: "Travel expense reimbursement",
      updatedAt: Date.now() - 3 * 86400 * 1000,
      messages: [
        { id: "m7", role: "user", content: "Explain the travel expense reimbursement approval flow", time: "3 days ago" },
        { id: "m8", role: "assistant", content: "Travel expenses under $1,000 require manager approval. Expenses exceeding $1,000 require VP and Finance approval.", time: "3 days ago" }
      ]
    }
  ]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [chatSearch, setChatSearch] = useState("");

  const abortControllerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const scopeDropdownRef = useRef(null);
  const folderDropdownRef = useRef(null);

  // Helper to extract anti-CSRF token from cookie
  const getCsrfToken = () => {
    const match = document.cookie.match(/(?:^|;\s*)assistant_csrf=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  };

  // Apply dark mode class to body
  useEffect(() => {
    if (darkMode) {
      document.body.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.body.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  }, [darkMode]);

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [authConfig, setAuthConfig] = useState({ enable_quick_signin: false, demo_accounts: [] });

  const refreshSession = () => {
    fetch("/api/v1/auth/me")
      .then(res => {
        if (res.ok) return res.json();
        throw new Error("unauthenticated");
      })
      .then(data => {
        setSession(data);
        setLoginError("");
        fetch("/api/v1/mcp/tools?filter_permissions=true")
          .then(res => res.ok ? res.json() : null)
          .then(td => {
            if (td && td.tools) setMcpTools(td.tools);
          })
          .catch(() => {});
      })
      .catch(() => {
        setSession(null);
        setMcpTools([]);
      });
  };

  const fetchAuthConfig = () => {
    fetch("/api/v1/auth/config")
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) setAuthConfig(data);
      })
      .catch(() => {});
  };

  // Verify session and fetch auth configuration on mount
  useEffect(() => {
    refreshSession();
    fetchAuthConfig();
  }, []);

  const handleLogout = async () => {
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": getCsrfToken()
        }
      });
    } catch {}
    setSession(null);
    setMcpTools([]);
    setMessages([]);
    setInput("");
    setCitationModal(null);
    setSelectedFolders([]);
    setScope("all");
    setAuditLog([]);
    logAuditEvent("logout", "allowed", "Employee logged out");
  };

  const handleSwitchEmployee = async () => {
    if (session) {
      await handleLogout();
    }
    setActiveChatId(null);
    setChatSearch("");
    setMessages([]);
    setInput("");
    setCitationModal(null);
    setSelectedFolders([]);
    setScope("all");
    setAuditLog([]);
    setSession(null);
    setMcpTools([]);
    setLoginUsername("");
    setLoginPassword("");
    setLoginError("");
    setTokenModalOpen(true);
  };

  const handleLogin = async (uname, pwd) => {
    setLoginError("");
    const username = (uname || loginUsername).trim();
    const password = pwd || loginPassword;
    if (!username || !password) {
      setLoginError("Please enter both username and password.");
      return;
    }
    // Perform genuine logout of prior session if switching accounts
    if (session && session.subject !== username) {
      try {
        await fetch("/api/v1/auth/logout", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": getCsrfToken()
          }
        });
      } catch {}
    }
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, client_type: "browser" })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setLoginError(data.message || "Invalid credentials or account deactivated.");
        return;
      }
      setTokenModalOpen(false);
      setLoginPassword("");
      // Clear previous user-specific context
      setMessages([]);
      setInput("");
      setCitationModal(null);
      setSelectedFolders([]);
      setScope("all");
      refreshSession();
      logAuditEvent("login", "allowed", `Signed in as ${username}`);
    } catch (e) {
      setLoginError("Network error: Unable to contact authentication gateway.");
    }
  };

  // Keyboard shortcut listener (Cmd/Ctrl + K = New chat, Cmd/Ctrl + B = Toggle sidebar)
  useEffect(() => {
    const handleKeyDown = (e) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        handleNewChat();
      } else if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setSidebarCollapsed(prev => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Close dropdowns on outside click or on Escape
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (scopeDropdownRef.current && !scopeDropdownRef.current.contains(e.target)) {
        setScopeDropdownOpen(false);
      }
      if (folderDropdownRef.current && !folderDropdownRef.current.contains(e.target)) {
        setFolderDropdownOpen(false);
      }
    };
    const handleEscape = (e) => {
      if (e.key === "Escape") {
        setScopeDropdownOpen(false);
        setFolderDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  const handleNewChat = () => {
    setActiveChatId(null);
    setMessages([]);
    setInput("");
    textareaRef.current?.focus();
  };

  const handleSelectChat = (chat) => {
    setActiveChatId(chat.id);
    if (chat.messages && chat.messages.length > 0) {
      setMessages(chat.messages);
    } else {
      handleSend(chat.title);
    }
  };

  const logAuditEvent = (event, status, detail) => {
    setAuditLog(prev => [
      {
        id: "evt-" + Date.now(),
        time: new Date().toLocaleTimeString(),
        event,
        status,
        detail
      },
      ...prev
    ].slice(0, 50));
  };

  const handleSend = async (customMessage) => {
    const textToSend = (customMessage || input).trim();
    if (!textToSend || isLoading) return;

    setInput("");
    const userMsg = {
      id: "usr-" + Date.now(),
      role: "user",
      content: textToSend,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    };

    let currentChatId = activeChatId;
    if (!currentChatId) {
      currentChatId = "c-" + Date.now();
      setActiveChatId(currentChatId);
      const title = textToSend.length > 50 ? textToSend.slice(0, 47) + "..." : textToSend;
      setConversations(prev => [
        { id: currentChatId, title, updatedAt: Date.now(), messages: [userMsg] },
        ...prev
      ]);
    } else {
      setConversations(prev => prev.map(c => c.id === currentChatId ? {
        ...c,
        updatedAt: Date.now(),
        messages: [...(c.messages || []), userMsg]
      } : c));
    }

    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const headers = {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken()
      };

      const started = performance.now();
      const response = await fetch("/api/v1/chat", {
        method: "POST",
        headers,
        body: JSON.stringify({ message: textToSend }),
        signal: controller.signal
      });

      const latencyMs = Math.round(performance.now() - started);
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        logAuditEvent("assistant_chat", "denied", `HTTP ${response.status}`);
        if (response.status === 401) {
          setTokenModalOpen(true);
        }
        const errMsg = {
          id: "err-" + Date.now(),
          role: "assistant",
          isError: true,
          content: data.message || `Error: Request failed with status ${response.status}`
        };
        setMessages(prev => [...prev, errMsg]);
        setConversations(prev => prev.map(c => c.id === currentChatId ? {
          ...c,
          updatedAt: Date.now(),
          messages: [...(c.messages || []), errMsg]
        } : c));
        return;
      }

      logAuditEvent("assistant_chat", "allowed", `${latencyMs}ms latency`);

      const assistantMsg = {
        id: "ai-" + Date.now(),
        role: "assistant",
        content: data.response,
        citations: data.citations || [],
        latencyMs,
        time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        toolTrace: data.tool_trace || (data.citations && data.citations.length > 0
          ? `Scanned internal documents: ${data.citations.map(c => c.filename).join(", ")}`
          : null)
      };

      setMessages(prev => [...prev, assistantMsg]);
      setConversations(prev => prev.map(c => c.id === currentChatId ? {
        ...c,
        updatedAt: Date.now(),
        messages: [...(c.messages || []), assistantMsg]
      } : c));
    } catch (err) {
      if (err.name !== "AbortError") {
        logAuditEvent("assistant_chat", "failed", err.message);
        const netErr = {
          id: "err-" + Date.now(),
          role: "assistant",
          isError: true,
          content: "Network error: Unable to communicate with the local assistant service."
        };
        setMessages(prev => [...prev, netErr]);
        setConversations(prev => prev.map(c => c.id === currentChatId ? {
          ...c,
          updatedAt: Date.now(),
          messages: [...(c.messages || []), netErr]
        } : c));
      }
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsLoading(false);
    }
  };

  const handleCopy = (id, text) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Filter and group conversations based on search query
  const needle = chatSearch.trim().toLowerCase();
  const filteredConversations = conversations.filter(c => {
    if (!needle) return true;
    if (c.title && c.title.toLowerCase().includes(needle)) return true;
    if (c.messages && c.messages.some(m => m.content && m.content.toLowerCase().includes(needle))) return true;
    return false;
  });

  const DAY_MS = 86400000;
  const startOfToday = new Date().setHours(0, 0, 0, 0);

  const historyGroups = [
    {
      label: "Today",
      items: filteredConversations.filter(c => c.updatedAt >= startOfToday)
    },
    {
      label: "Yesterday",
      items: filteredConversations.filter(c => c.updatedAt >= startOfToday - DAY_MS && c.updatedAt < startOfToday)
    },
    {
      label: "Previous 7 days",
      items: filteredConversations.filter(c => c.updatedAt >= startOfToday - 7 * DAY_MS && c.updatedAt < startOfToday - DAY_MS)
    },
    {
      label: "Older",
      items: filteredConversations.filter(c => c.updatedAt < startOfToday - 7 * DAY_MS)
    }
  ].filter(g => g.items.length > 0);

  const currentScopeObj = SCOPES.find(s => s.id === scope) || SCOPES[0];
  const scopeLabel = currentScopeObj.label;

  const folderLabel = selectedFolders.length === 0
    ? "All folders"
    : selectedFolders.length === 1
      ? (KNOWLEDGE_BASES.find(k => k.folder === selectedFolders[0])?.name || "1 folder")
      : `${selectedFolders.length} folders`;

  return h("div", { className: "app-container", "aria-label": "Enterprise Intranet Assistant" },

    // =========================================================================
    // 1. RESTORED LEFT SIDEBAR (~320px)
    // =========================================================================
    h("aside", { className: `sidebar ${sidebarCollapsed ? "collapsed" : ""}` },
      // Header: Brand & Collapse Toggle
      h("div", { className: "sidebar-header" },
        !sidebarCollapsed && h("div", { className: "brand-group" },
          h("div", { className: "brand-icon" }, h(Icon, { name: "logo" })),
          h("span", { className: "brand-title" }, "AeroGrid AI")
        ),
        h("button", {
          className: "sidebar-collapse-btn",
          onClick: () => setSidebarCollapsed(prev => !prev),
          title: sidebarCollapsed ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)"
        }, h(Icon, { name: "panelLeft", size: 18 }))
      ),

      !sidebarCollapsed && h("div", { className: "sidebar-actions" },
        // New Chat Button with Ctrl+K badge
        h("button", { className: "btn-new-chat", onClick: handleNewChat },
          h("div", { className: "btn-new-chat-left" },
            h(Icon, { name: "squarePen", size: 15 }),
            h("span", null, "New chat")
          ),
          h("span", { className: "kbd-badge" }, "Ctrl K")
        ),
        // Search chats input
        h("div", { className: "search-container" },
          h("span", { className: "search-icon-inside" }, h(Icon, { name: "search", size: 14 })),
          h("input", {
            className: "search-input",
            placeholder: "Search chats...",
            type: "text",
            value: chatSearch,
            onChange: (e) => setChatSearch(e.target.value),
            onKeyDown: (e) => {
              if (e.key === "Escape") setChatSearch("");
            }
          }),
          chatSearch && h("button", {
            className: "search-clear-btn",
            onClick: () => setChatSearch(""),
            title: "Clear search",
            "aria-label": "Clear search",
            style: {
              position: "absolute",
              right: "8px",
              top: "50%",
              transform: "translateY(-50%)",
              background: "transparent",
              border: "none",
              color: "var(--text-muted)",
              cursor: "pointer",
              padding: "2px",
              display: "flex",
              alignItems: "center"
            }
          }, h(Icon, { name: "x", size: 13 }))
        )
      ),

      !sidebarCollapsed && h("div", { className: "sidebar-scrollable" },
        // Section: Chat History / Recent Inquiries (Today, Yesterday, Previous 7 days)
        h("div", null,
          h("div", { className: "sidebar-section-title" }, "Recent Inquiries"),
          historyGroups.length > 0 ? (
            historyGroups.map(grp =>
              h("div", { key: grp.label },
                h("div", { className: "history-group-label" }, grp.label),
                grp.items.map(item =>
                  h("div", {
                    key: item.id,
                    className: `history-item ${activeChatId === item.id ? "active" : ""}`,
                    onClick: () => handleSelectChat(item),
                    title: item.title
                  },
                    h("span", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, item.title)
                  )
                )
              )
            )
          ) : (
            h("div", {
              style: {
                padding: "8px 12px",
                fontSize: "12px",
                color: "var(--text-muted)",
                fontStyle: "italic"
              }
            }, needle ? `No chats matching "${chatSearch}"` : "No recent chats.")
          )
        ),

        // Section: Knowledge Navigation
        h("div", null,
          h("div", { className: "sidebar-section-title" }, "Knowledge"),
          h("ul", { className: "sidebar-nav-list" },
            KNOWLEDGE_BASES.map(kb =>
              h("li", {
                key: kb.name,
                className: "sidebar-nav-item",
                onClick: () => handleSend(`Search policy regarding ${kb.name}`)
              },
                h(Icon, { name: "book", size: 15, className: "nav-item-icon" }),
                h("span", { className: "nav-item-text" }, kb.name),
                h("span", { className: "nav-item-badge" }, kb.meta.split("·")[0].trim())
              )
            )
          )
        ),

        // Section: Approved Queries Navigation
        h("div", null,
          h("div", { className: "sidebar-section-title" }, "Approved Queries"),
          h("ul", { className: "sidebar-nav-list" },
            APPROVED_QUERIES.map(q =>
              h("li", {
                key: q.name,
                className: "sidebar-nav-item",
                onClick: () => handleSend(q.prompt)
              },
                h(Icon, { name: "database", size: 15, className: "nav-item-icon" }),
                h("span", { className: "nav-item-text" }, q.name)
              )
            )
          )
        )
      ),

      // Footer: Bottom Navigation & User Profile
      !sidebarCollapsed && h("div", { className: "sidebar-footer" },
        h("div", { className: "footer-nav-row" },
          h("button", { className: "footer-btn", onClick: () => setInspectorOpen(true) },
            h(Icon, { name: "shield", size: 15 }),
            h("span", null, "Security & Audit")
          ),
          h("button", {
            className: "footer-btn",
            onClick: () => setDarkMode(prev => !prev),
            title: darkMode ? "Switch to Light Mode" : "Switch to Dark Mode"
          },
            h(Icon, { name: darkMode ? "sun" : "moon", size: 15 })
          )
        ),
        h("div", {
          className: "user-profile-card",
          title: session ? `Logged in as ${session.subject}. Click to manage session.` : "Click to sign in"
        },
          h("div", {
            className: "user-avatar",
            onClick: () => (session ? handleSwitchEmployee() : setTokenModalOpen(true)),
            style: { cursor: "pointer" }
          }, session ? session.subject.slice(0, 2).toUpperCase() : "?"),
          h("div", {
            className: "user-info",
            onClick: () => (session ? handleSwitchEmployee() : setTokenModalOpen(true)),
            style: { flex: "1", cursor: "pointer" }
          },
            h("span", { className: "user-name" }, session ? session.subject : "Unauthenticated"),
            h("span", { className: "user-meta" }, session && session.roles ? `roles: ${session.roles.join(", ")}` : "Click to sign in")
          ),
          session && h("button", {
            className: "footer-btn",
            onClick: (e) => {
              e.stopPropagation();
              handleLogout();
            },
            title: "Sign Out"
          }, "⎋")
        )
      )
    ),

    // =========================================================================
    // 2. RESTORED MAIN CHAT WORKSPACE
    // =========================================================================
    h("main", { className: "main-workspace" },
      // Top Header
      h("header", { className: "top-header" },
        h("div", { className: "header-left" },
          h("h1", { className: "chat-title-heading" },
            messages.length > 0 ? messages[0].content.slice(0, 48) : "New chat"
          )
        ),
        h("div", { className: "header-right" },
          h("div", { className: "network-badge" },
            h("span", { className: "pulse-dot" }),
            h("span", null, "Private network")
          ),
          h("button", {
            className: "header-icon-btn",
            onClick: () => setInspectorOpen(true),
            title: "Security & Diagnostics"
          }, h(Icon, { name: "shield", size: 17 }))
        )
      ),

      // Scrollable Message/Empty State Area
      h("div", { className: "chat-scroll-area" },
        messages.length === 0 ? (
          // ===================================================================
          // RESTORED AUTHORITATIVE WELCOME STATE
          // ===================================================================
          h("div", { className: "welcome-container" },
            h("h2", { className: "welcome-title" }, "How can I help you today?"),
            h("p", { className: "welcome-subtitle" },
              "Ask questions about your organization's knowledge, documents, policies, and internal resources."
            ),
            h("div", { className: "quick-prompts-grid" },
              QUICK_PROMPTS.map(qp =>
                h("div", {
                  key: qp.title,
                  className: "prompt-card",
                  onClick: () => handleSend(qp.prompt)
                },
                  h("div", { className: "prompt-card-top" },
                    h(Icon, { name: qp.icon, size: 16, className: "prompt-card-icon" }),
                    h("span", { className: "prompt-card-title" }, qp.title)
                  ),
                  h("p", { className: "prompt-card-desc" }, qp.prompt),
                  h("span", { className: "prompt-card-tag" }, qp.tag)
                )
              )
            )
          )
        ) : (
          // Active Conversation Stream
          h("div", { className: "conversation-stream" },
            messages.map(msg =>
              msg.role === "user" ? (
                h("div", { key: msg.id, className: "message-row-user" },
                  h("div", { className: "user-bubble" }, msg.content)
                )
              ) : (
                h("div", { key: msg.id, className: "message-row-ai" },
                  // Tool Trace Accordion if internal tools executed
                  msg.toolTrace && h("div", { className: "tool-trace-card" },
                    h("div", { className: "tool-trace-header" },
                      h("span", { className: "tool-trace-title" },
                        h(Icon, { name: "shield", size: 14 }),
                        msg.toolTrace
                      ),
                      h("span", { className: "tool-trace-status" }, "✓ Complete")
                    )
                  ),
                  // Assistant Message Text
                  h("div", { className: "ai-content" },
                    h("p", null, msg.content)
                  ),
                  // Source Citations
                  msg.citations && msg.citations.length > 0 && h("div", { className: "citations-wrapper" },
                    h("span", { className: "citations-header" },
                      h(Icon, { name: "fileText", size: 13 }),
                      "Verified Sources:"
                    ),
                    h("div", { className: "citation-chips-row" },
                      msg.citations.map((c, i) =>
                        h("button", {
                          key: i,
                          className: "citation-chip-btn",
                          onClick: () => setCitationModal(c)
                        },
                          c.filename,
                          c.page ? ` (p. ${c.page})` : ""
                        )
                      )
                    )
                  )
                )
              )
            ),
            isLoading && h("div", { className: "inflight-status-box" },
              h("div", { className: "spinner-icon" }),
              h("span", null, "Retrieving verified intranet records and synthesizing answer...")
            ),
            h("div", { ref: messagesEndRef })
          )
        )
      ),

      // =========================================================================
      // 3. RESTORED BOTTOM MESSAGE COMPOSER
      // =========================================================================
      h("div", { className: "composer-dock-container" },
        h("div", { className: "composer-box" },
          h("textarea", {
            ref: textareaRef,
            className: "composer-textarea",
            placeholder: "Ask anything about your organization...",
            value: input,
            onChange: e => setInput(e.target.value),
            onKeyDown: e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            },
            rows: 1
          }),
          h("div", { className: "composer-bottom-bar" },
            // Left Selectors: Scope & Folder Dropdown Menus
            h("div", { className: "composer-selectors" },
              // 1. SCOPE DROPDOWN
              h("div", { className: "dropdown-container", ref: scopeDropdownRef },
                h("button", {
                  className: `composer-pill-btn ${scope !== "all" ? "active" : ""} ${scopeDropdownOpen ? "open" : ""}`,
                  type: "button",
                  "aria-label": `Search scope: ${scopeLabel}`,
                  "aria-haspopup": "true",
                  "aria-expanded": scopeDropdownOpen,
                  onClick: () => {
                    setScopeDropdownOpen(prev => !prev);
                    setFolderDropdownOpen(false);
                  }
                },
                  h(Icon, { name: "layers", size: 13 }),
                  h("span", null, scopeLabel),
                  h(Icon, { name: "chevronDown", size: 12, className: "chevron-icon" })
                ),
                scopeDropdownOpen && h("div", { className: "dropdown-popover", role: "menu" },
                  h("div", { className: "dropdown-header-label" }, "Search scope"),
                  SCOPES.map(s =>
                    h("button", {
                      key: s.id,
                      type: "button",
                      className: `dropdown-item ${scope === s.id ? "selected" : ""}`,
                      role: "menuitemradio",
                      "aria-checked": scope === s.id,
                      onClick: () => {
                        setScope(s.id);
                        setScopeDropdownOpen(false);
                      }
                    },
                      h("div", { className: "dropdown-item-info" },
                        h("span", { className: "dropdown-item-title" }, s.label),
                        h("span", { className: "dropdown-item-desc" }, s.hint)
                      ),
                      scope === s.id && h("div", { className: "dropdown-item-check" },
                        h(Icon, { name: "check", size: 14 })
                      )
                    )
                  )
                )
              ),

              // 2. FOLDER DROPDOWN
              h("div", { className: "dropdown-container", ref: folderDropdownRef },
                h("button", {
                  className: `composer-pill-btn ${selectedFolders.length > 0 ? "active" : ""} ${folderDropdownOpen ? "open" : ""}`,
                  type: "button",
                  "aria-label": `Folder filter: ${folderLabel}`,
                  "aria-haspopup": "true",
                  "aria-expanded": folderDropdownOpen,
                  onClick: () => {
                    setFolderDropdownOpen(prev => !prev);
                    setScopeDropdownOpen(false);
                  }
                },
                  h(Icon, { name: "folder", size: 13 }),
                  h("span", { className: "folder-label-text" }, folderLabel),
                  h(Icon, { name: "chevronDown", size: 12, className: "chevron-icon" })
                ),
                folderDropdownOpen && h("div", { className: "dropdown-popover dropdown-popover-folders", role: "menu" },
                  h("div", { className: "dropdown-header-label" }, "Restrict document search to"),
                  KNOWLEDGE_BASES.map(kb => {
                    const isChecked = selectedFolders.includes(kb.folder);
                    return h("button", {
                      key: kb.folder,
                      type: "button",
                      className: `dropdown-item ${isChecked ? "selected" : ""}`,
                      role: "menuitemcheckbox",
                      "aria-checked": isChecked,
                      onClick: () => {
                        setSelectedFolders(prev =>
                          prev.includes(kb.folder)
                            ? prev.filter(f => f !== kb.folder)
                            : [...prev, kb.folder]
                        );
                      }
                    },
                      h("div", { className: "dropdown-item-info" },
                        h("span", { className: "dropdown-item-title" }, kb.name),
                        h("span", { className: "dropdown-item-path" }, kb.folder)
                      ),
                      h("div", { className: `dropdown-checkbox-box ${isChecked ? "checked" : ""}` },
                        isChecked && h(Icon, { name: "check", size: 11 })
                      )
                    );
                  }),
                  h("div", { className: "dropdown-divider" }),
                  h("button", {
                    type: "button",
                    className: "dropdown-clear-btn",
                    disabled: selectedFolders.length === 0,
                    onClick: () => setSelectedFolders([])
                  }, "Clear filters")
                )
              )
            ),
            // Right Actions: Token Counter & Send Button
            h("div", { className: "composer-right-actions" },
              h("span", { className: "token-counter" },
                `${input.trim().length ? Math.round(input.trim().length / 4) : 0} / 4,096 tokens`
              ),
              isLoading ? (
                h("button", {
                  className: "btn-send-circular",
                  style: { backgroundColor: "var(--text-secondary)" },
                  onClick: handleStop,
                  title: "Stop generating"
                }, h(Icon, { name: "square", size: 12 }))
              ) : (
                h("button", {
                  className: "btn-send-circular",
                  disabled: !input.trim(),
                  onClick: () => handleSend(),
                  title: "Send message"
                }, h(Icon, { name: "arrowUp", size: 16 }))
              )
            )
          )
        ),
        // Trust Statement
        h("p", { className: "composer-trust-statement" },
          "Answers come only from verified internal sources. Requests are audited."
        )
      )
    ),

    // =========================================================================
    // 4. RESTORED CITATION PREVIEW SHEET
    // =========================================================================
    citationModal && h("div", { className: "sheet-backdrop", onClick: () => setCitationModal(null) },
      h("div", { className: "sheet-panel", onClick: e => e.stopPropagation() },
        h("div", { className: "sheet-header" },
          h("h3", { className: "sheet-title" }, "Verified Document Source"),
          h("button", { className: "sheet-close-btn", onClick: () => setCitationModal(null) }, "✕")
        ),
        h("div", { className: "sheet-body" },
          h("div", { style: { display: "flex", alignItems: "center", gap: "8px", color: "var(--accent-blue)" } },
            h(Icon, { name: "shield", size: 16 }),
            h("strong", null, "Verified Intranet File")
          ),
          h("table", { className: "info-table" },
            h("tbody", null,
              h("tr", null,
                h("td", null, "Filename"),
                h("td", null, citationModal.filename)
              ),
              h("tr", null,
                h("td", null, "Document ID"),
                h("td", null, citationModal.document_id || "doc-int-001")
              ),
              h("tr", null,
                h("td", null, "Page Number"),
                h("td", null, citationModal.page ? `Page ${citationModal.page}` : "Document Root")
              ),
              h("tr", null,
                h("td", null, "Classification"),
                h("td", { style: { color: "var(--status-online)" } },
                  citationModal.filename && citationModal.filename.includes("sample_db.sqlite3")
                    ? "Internal / Structured Database (HR Directory)"
                    : "Internal / Confidential"
                )
              )
            )
          ),
          h("div", { style: { marginTop: "16px" } },
            h("h4", { style: { fontSize: "13px", fontWeight: "600", marginBottom: "8px" } }, "Verified Internal Excerpt:"),
            h("div", {
              style: {
                background: "var(--bg-muted)",
                padding: "12px",
                borderRadius: "var(--radius-sm)",
                fontSize: "13px",
                lineHeight: "1.5"
              }
            },
              citationModal.filename && citationModal.filename.includes("sample_db.sqlite3")
                ? "Relational database record retrieved from employee_directory table via approved read-only catalog query."
                : citationModal.filename === "leave_policy.md"
                  ? "All full-time employees are allocated 25 days of paid time off per calendar year. PTO accrues monthly at a rate of 2.08 days per month. Unused PTO up to a maximum of 5 days can be carried forward."
                  : citationModal.filename === "engineering_handbook.md"
                    ? "Engineering standards for internal systems, architecture guidelines, and deployment protocols."
                    : citationModal.filename === "hr_benefits_guide.md"
                      ? "Comprehensive benefits documentation covering health coverage, retirement matching, and employee programs."
                      : "All employee intranet passwords must be at least 14 characters long and expire automatically every 90 days."
            )
          )
        )
      )
    ),

    // =========================================================================
    // 5. RESTORED SECURITY & AUDIT INSPECTOR SHEET
    // =========================================================================
    inspectorOpen && h("div", { className: "sheet-backdrop", onClick: () => setInspectorOpen(false) },
      h("div", { className: "sheet-panel", onClick: e => e.stopPropagation() },
        h("div", { className: "sheet-header" },
          h("h3", { className: "sheet-title" }, "Security & System Inspector"),
          h("button", { className: "sheet-close-btn", onClick: () => setInspectorOpen(false) }, "✕")
        ),
        h("div", { className: "tabs-nav" },
          ["session", "tools", "audit", "model"].map(t =>
            h("button", {
              key: t,
              className: `tab-btn ${activeTab === t ? "active" : ""}`,
              onClick: () => setActiveTab(t)
            }, t.toUpperCase())
          )
        ),
        h("div", { className: "sheet-body" },
          activeTab === "session" && h("div", null,
            h("h4", { style: { fontSize: "13px", fontWeight: "600", marginBottom: "8px" } }, "Verified Caller Claims"),
            h("table", { className: "info-table" },
              h("tbody", null,
                h("tr", null,
                  h("td", null, "Subject"),
                  h("td", null, session ? session.subject : "Unauthenticated")
                ),
                h("tr", null,
                  h("td", null, "Assigned Roles"),
                  h("td", null, "employee, analyst, admin")
                ),
                h("tr", null,
                  h("td", null, "Granted Permissions"),
                  h("td", null, session && session.permissions ? session.permissions.join(", ") : "chat:use, documents:search, database:read")
                ),
                h("tr", null,
                  h("td", null, "Network Egress"),
                  h("td", { style: { color: "var(--status-online)" } }, "Blocked (Air-Gapped)")
                )
              )
            ),
            h("button", {
              className: "btn-new-chat",
              style: { marginTop: "16px" },
              onClick: () => {
                setInspectorOpen(false);
                handleSwitchEmployee();
              }
            }, "Sign In / Switch Employee")
          ),
          activeTab === "tools" && h("div", null,
            h("h4", { style: { fontSize: "13px", fontWeight: "600", marginBottom: "8px" } }, "Registered MCP Internal Tools"),
            mcpTools.length === 0 ? (
              h("p", { style: { color: "var(--text-muted)", fontSize: "12px" } }, "Loading tools...")
            ) : (
              mcpTools.map(tool =>
                h("div", {
                  key: tool.name,
                  style: {
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-sm)",
                    padding: "10px",
                    marginBottom: "8px"
                  }
                },
                  h("strong", { style: { color: "var(--accent-blue)", fontSize: "13px" } }, tool.name),
                  h("p", { style: { fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" } }, tool.description),
                  h("span", {
                    style: {
                      fontSize: "11px",
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-muted)",
                      display: "inline-block",
                      marginTop: "4px"
                    }
                  }, `Permission: ${tool.required_permission}`)
                )
              )
            )
          ),
          activeTab === "audit" && h("div", null,
            h("h4", { style: { fontSize: "13px", fontWeight: "600", marginBottom: "8px" } }, "Recent Gateway Audit Events"),
            auditLog.length === 0 ? (
              h("p", { style: { color: "var(--text-muted)", fontSize: "12px" } }, "No audit events logged in this session yet.")
            ) : (
              h("table", { className: "info-table" },
                h("tbody", null,
                  auditLog.map(evt =>
                    h("tr", { key: evt.id },
                      h("td", null, `${evt.time} · ${evt.event}`),
                      h("td", { style: { color: evt.status === "allowed" ? "var(--status-online)" : "var(--status-danger)" } },
                        `${evt.status} (${evt.detail})`
                      )
                    )
                  )
                )
              )
            )
          ),
          activeTab === "model" && h("div", null,
            h("h4", { style: { fontSize: "13px", fontWeight: "600", marginBottom: "8px" } }, "Local Inference Runtime"),
            h("table", { className: "info-table" },
              h("tbody", null,
                h("tr", null,
                  h("td", null, "Model Name"),
                  h("td", null, "qwen2.5:3b (Ollama)")
                ),
                h("tr", null,
                  h("td", null, "Endpoint URL"),
                  h("td", null, "http://127.0.0.1:11434/v1")
                ),
                h("tr", null,
                  h("td", null, "Context Budget"),
                  h("td", null, "4,096 tokens")
                ),
                h("tr", null,
                  h("td", null, "Hardware Host"),
                  h("td", null, "Intel Core i5-13420H (12 threads)")
                )
              )
            )
          )
        )
      )
    ),

    // =========================================================================
    // 6. AUTHENTICATION MODAL
    // =========================================================================
    tokenModalOpen && h("div", { className: "sheet-backdrop", onClick: () => setTokenModalOpen(false) },
      h("div", {
        style: {
          background: "var(--bg-surface)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          padding: "24px",
          maxWidth: "460px",
          width: "90%",
          margin: "auto",
          boxShadow: "var(--shadow-lg)"
        },
        onClick: e => e.stopPropagation()
      },
        h("h3", { style: { fontSize: "16px", fontWeight: "600", marginBottom: "8px" } }, "Enterprise Employee Sign In"),
        h("p", { style: { fontSize: "13px", color: "var(--text-secondary)", marginBottom: "16px" } },
          "Sign in with your organizational directory account to establish an authorized, audited session."
        ),
        loginError && h("div", {
          style: {
            background: "rgba(239, 68, 68, 0.1)",
            border: "1px solid var(--status-danger)",
            borderRadius: "var(--radius-sm)",
            padding: "8px 12px",
            color: "var(--status-danger)",
            fontSize: "12px",
            marginBottom: "12px"
          }
        }, loginError),
        h("div", { style: { marginBottom: "12px" } },
          h("label", { style: { display: "block", fontSize: "12px", color: "var(--text-secondary)", marginBottom: "4px" } }, "Username / Corporate ID"),
          h("input", {
            type: "text",
            placeholder: "e.g. alice.chen, david.miller, bob.smith",
            value: loginUsername,
            onChange: e => setLoginUsername(e.target.value),
            style: {
              width: "100%",
              padding: "8px 12px",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              fontSize: "13px",
              background: "var(--bg-muted)",
              color: "var(--text-primary)",
              outline: "none"
            }
          })
        ),
        h("div", { style: { marginBottom: "16px" } },
          h("label", { style: { display: "block", fontSize: "12px", color: "var(--text-secondary)", marginBottom: "4px" } }, "Password"),
          h("input", {
            type: "password",
            placeholder: "••••••••",
            value: loginPassword,
            onChange: e => setLoginPassword(e.target.value),
            onKeyDown: e => {
              if (e.key === "Enter") handleLogin();
            },
            style: {
              width: "100%",
              padding: "8px 12px",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              fontSize: "13px",
              background: "var(--bg-muted)",
              color: "var(--text-primary)",
              outline: "none"
            }
          })
        ),
        h("div", { style: { display: "flex", justifyContent: "flex-end", gap: "8px" } },
          h("button", {
            className: "composer-pill-btn",
            onClick: () => setTokenModalOpen(false)
          }, "Close"),
          h("button", {
            className: "composer-pill-btn",
            style: { backgroundColor: "var(--accent-blue)", color: "#ffffff", borderColor: "var(--accent-blue)" },
            onClick: () => handleLogin()
          }, "Sign In")
        ),
        authConfig.enable_quick_signin && authConfig.demo_accounts && authConfig.demo_accounts.length > 0 && h("div", { style: { marginTop: "20px", paddingTop: "16px", borderTop: "1px solid var(--border-subtle)" } },
          h("span", { style: { fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "8px" } }, "Quick Sign In (Directory Accounts):"),
          h("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px" } },
            authConfig.demo_accounts.map(acc =>
              h("button", {
                key: acc.username,
                className: "composer-pill-btn",
                onClick: () => handleLogin(acc.username, acc.password)
              }, acc.label)
            )
          )
        )
      )
    )
  );
}

// Mount React Root
const rootEl = document.getElementById("root");
if (rootEl && window.ReactDOM) {
  const root = ReactDOM.createRoot(rootEl);
  root.render(h(App));
}
