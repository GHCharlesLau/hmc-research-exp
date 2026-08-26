function loadChatConfig() {
    const el = document.getElementById('chat-config');
    return el ? JSON.parse(el.textContent) : {};
}

function chatApp() {
    const cfg = loadChatConfig();
    const initialMessages = cfg.messages || [];
    const minTurns = cfg.minTurns || 0;

    return {
        messages: initialMessages,
        inputText: '',
        turnCount: initialMessages.length,
        sharedTurns: cfg.initialSharedTurns || 0,
        timeRemaining: cfg.timeRemaining || 0,
        chatEnded: false,
        showEndBanner: false,
        showRetryDialog: !!cfg.showRetryDialog,
        endReason: '',
        partnerLeft: false,
        partnerLeftName: '',
        ws: null,
        reconnectAttempts: 0,
        maxReconnect: 5,
        timerInterval: null,
        wsStatus: 'connecting',
        partnerAvatar: cfg.partnerAvatar,
        partnerName: cfg.partnerName,
        userName: cfg.userName,
        userAvatar: cfg.userAvatar,
        roomId: cfg.roomId,
        roomType: cfg.roomType || '',

        init() {
            if (this.showRetryDialog) {
                this.chatEnded = true;
                this.$el.querySelector('[x-show="showRetryDialog"]')?.removeAttribute('x-transition');
                this.$nextTick(() => this.scrollToBottom());
                return;
            }

            this.timerInterval = setInterval(() => {
                if (this.timeRemaining > 0) {
                    this.timeRemaining--;
                    if (this.timeRemaining <= 0) {
                        this.handleChatEnd('timeout');
                    }
                }
            }, 1000);

            this.connectWebSocket();
            this.$nextTick(() => this.scrollToBottom());
        },

        connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.wsStatus = 'connecting...';
            this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat/${this.roomId}`);

            this.ws.onopen = () => {
                const wasReconnect = this.reconnectAttempts > 0;
                this.reconnectAttempts = 0;
                this.wsStatus = 'connected';
                if (wasReconnect && this.messages.length > 0) {
                    this.ws.send(JSON.stringify({ type: 'history_request' }));
                }
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'message') {
                        const pending = data.sender_role === 'user'
                            ? this.messages.find(m => m.pending && m.sender_role === 'user' && m.text === data.text)
                            : null;
                        if (pending) {
                            pending.msg_id = data.msg_id;
                            pending.turn_number = data.turn_number;
                            pending.pending = false;
                        } else if (this.isDuplicateMessage(data)) {
                            console.warn('[chat dedup] Dropped duplicate:', data.msg_id, data.turn_number, data.sender_role);
                        } else {
                            this.messages.push(data);
                            this.turnCount = this.messages.length;
                            this.$nextTick(() => this.scrollToBottom());
                        }
                        if (data.shared_turns !== undefined && data.shared_turns > this.sharedTurns) {
                            this.sharedTurns = data.shared_turns;
                        }
                    } else if (data.type === 'chat_end') {
                        this.handleChatEnd(data.reason);
                    } else if (data.type === 'partner_left') {
                        this.partnerLeft = true;
                        this.partnerLeftName = this.partnerName;
                        this.$nextTick(() => this.scrollToBottom());
                    } else if (data.type === 'error') {
                        console.error('Chat error:', data.message);
                    }
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e, event.data);
                }
            };

            this.ws.onclose = () => {
                if (!this.chatEnded) {
                    if (this.reconnectAttempts < this.maxReconnect) {
                        this.wsStatus = 'reconnecting...';
                        this.reconnectAttempts++;
                        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
                        setTimeout(() => this.connectWebSocket(), delay);
                    } else {
                        this.wsStatus = 'disconnected';
                    }
                }
            };

            this.ws.onerror = (event) => {
                console.error('WebSocket error:', event);
                this.wsStatus = 'error';
            };
        },

        isDuplicateMessage(data) {
            return this.messages.some(m => {
                if (m.pending) return false;
                if (data.msg_id && m.msg_id && m.msg_id === data.msg_id) return true;
                return m.turn_number === data.turn_number
                    && m.sender_role === data.sender_role
                    && m.text === data.text;
            });
        },

        sendMessage() {
            const text = this.inputText.trim();
            if (!text || this.chatEnded || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

            const clientId = 'local-' + Date.now() + '-' + Math.random().toString(36).slice(2);
            this.messages.push({
                client_id: clientId,
                msg_id: clientId,
                sender_role: 'user',
                text,
                turn_number: null,
                pending: true,
            });
            this.turnCount = this.messages.length;
            this.ws.send(JSON.stringify({ type: 'message', text }));
            this.inputText = '';
            this.$nextTick(() => this.scrollToBottom());
            this.$refs.chatInput.focus();
        },

        handleChatEnd(reason) {
            if (this.chatEnded) return;
            this.chatEnded = true;
            clearInterval(this.timerInterval);

            if (this.sharedTurns < minTurns) {
                this.showRetryDialog = true;
                this.$nextTick(() => this.scrollToBottom());
                return;
            }

            this.endReason = reason === 'timeout' ? 'Time is up.' :
                             reason === 'max_turns' ? 'Maximum turns reached.' : '';
            this.showEndBanner = true;
            this.$nextTick(() => this.scrollToBottom());

            setTimeout(() => {
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = reason === 'timeout' ? '/chat/end?timeout=1' : '/chat/end';
                document.body.appendChild(form);
                form.submit();
            }, 5000);
        },

        async endChat() {
            if (this.sharedTurns < minTurns || this.chatEnded) return;
            if (confirm('Are you sure you want to end the conversation?')) {
                this.chatEnded = true;
                clearInterval(this.timerInterval);
                if (this.ws) this.ws.close();
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/chat/end';
                document.body.appendChild(form);
                form.submit();
            }
        },

        leaveChat() {
            if (this.chatEnded) return;
            this.chatEnded = true;
            clearInterval(this.timerInterval);
            if (this.ws) this.ws.close();

            if (this.sharedTurns < minTurns) {
                this.showRetryDialog = true;
                return;
            }

            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/chat/end?partner_left=1';
            document.body.appendChild(form);
            form.submit();
        },

        timeoutContinue() {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/chat/end?timeout=1&retry=1';
            document.body.appendChild(form);
            form.submit();
        },

        timeoutDropout() {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/chat/end?timeout=1&dropout=1';
            document.body.appendChild(form);
            form.submit();
        },

        scrollToBottom() {
            const el = this.$refs.messages;
            if (el) el.scrollTop = el.scrollHeight;
        },

        formatTime(seconds) {
            const m = Math.floor(seconds / 60);
            const s = seconds % 60;
            return `${m}:${s.toString().padStart(2, '0')}`;
        }
    };
}
