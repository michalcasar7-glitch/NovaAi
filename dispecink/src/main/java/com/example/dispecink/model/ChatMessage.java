package com.example.dispecink.model;

import lombok.Data;

@Data
public class ChatMessage {
    private String content;
    private String sender;
    private String recipient;  // Pro multi-chat: cílový agent nebo skupina
    private String timestamp;
    private String mode;  // "optimal", "proxy", "reevaluate"
}