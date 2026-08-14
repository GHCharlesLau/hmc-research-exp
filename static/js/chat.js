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
                        const exists = this.messages.some(m =>
                            m.turn_number === data.turn_number && m.sender_role === data.sender_role
                        );
                        if (!exists) {
                            this.messages.push(data);
                            this.turnCount = this.messages.length;
                            if (data.shared_turns !== undefined && data.shared_turns > this.sharedTurns) {
                                this.sharedTurns = data.shared_turns;
                            }
                            this.$nextTick(() => this.scrollToBottom());
                        } else {
                            console.warn('[HHC dedup] Dropped duplicate:', data.turn_number, data.sender_role);
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

        sendMessage() {
            const text = this.inputText.trim();
            if (!text || this.chatEnded || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

            this.ws.send(JSON.stringify({ type: 'message', text }));
            this.inputText = '';
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
