package com.example.dispecink.controller;

import com.example.dispecink.model.ChatMessage;
import com.example.dispecink.service.ChatService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.SendTo;
import org.springframework.stereotype.Controller;

@Controller
public class ChatController {

    @Autowired
    private ChatService chatService;

    @MessageMapping("/chat")
    @SendTo("/topic/messages")  // Broadcast do multi-chat
    public ChatMessage handleMessage(ChatMessage message) {
        // Řízení podle AKP režimu
        return chatService.processMessage(message);
    }

    @MessageMapping("/private-chat")
    public void handlePrivateMessage(ChatMessage message) {
        // Pro proxy režim: Přímé řízení
        chatService.processPrivateMessage(message);
    }
}